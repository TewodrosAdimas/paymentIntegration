import json
import uuid
import hmac
import hashlib
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import (
    JsonResponse,
    HttpResponseBadRequest,
    HttpResponseServerError,
    HttpResponse,
)
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PaymentTransaction

CHAPA_INITIALIZE_URL = getattr(
    settings, "CHAPA_INITIALIZE_URL", "https://api.chapa.co/v1/transaction/initialize"
)


def _build_chapa_payload(request, tx_ref, amount_str):
    """Construct the payload for the Chapa API request."""
    callback_url = request.build_absolute_uri(reverse("payments:chapa_webhook"))
    return_url = request.build_absolute_uri(reverse("payments:payment_callback"))

    return {
        "amount": amount_str,
        "currency": "ETB",
        "email": request.POST.get("email", "test@gmail.com"),
        "first_name": request.POST.get("first_name", "Test"),
        "last_name": request.POST.get("last_name", "User"),
        "phone_number": request.POST.get("phone_number", "0911111111"),
        "tx_ref": tx_ref,
        "callback_url": callback_url,
        "return_url": return_url,
        "customization": {
            "title": "Awesome Payment",
            "description": f"OrderRef {tx_ref}",
        },
    }


def _create_transaction(request, tx_ref, amount_str):
    """Create a new PaymentTransaction in the database."""
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid amount: {e}")

    return PaymentTransaction.objects.create(
        tx_ref=tx_ref,
        amount=amount,
        currency="ETB",
        email=request.POST.get("email", "test@gmail.com"),
        first_name=request.POST.get("first_name", "Test"),
        last_name=request.POST.get("last_name", "User"),
        phone_number=request.POST.get("phone_number", "0911111111"),
        status="pending",
    )


def initiate_payment_view(request):
    if request.method == "POST":
        tx_ref = f"tx_{uuid.uuid4().hex[:16]}"
        amount_str = request.POST.get("amount", "10.00")

        try:
            transaction = _create_transaction(request, tx_ref, amount_str)
        except ValueError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            print(f"Error creating transaction: {e}")
            return HttpResponseServerError("Transaction creation failed.")

        payload = _build_chapa_payload(request, tx_ref, amount_str)
        headers = {
            "Authorization": f"Bearer {settings.CHAPA_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                CHAPA_INITIALIZE_URL, headers=headers, json=payload, timeout=15
            )
            response_data = response.json()

            if response.ok and response_data.get("status") == "success":
                checkout_url = response_data.get("data", {}).get("checkout_url")
                if checkout_url:
                    return redirect(checkout_url)

            transaction.status = "failed"
            transaction.save()
            return HttpResponseServerError("Failed to initialize payment.")
        except requests.exceptions.RequestException as e:
            print(f"Chapa API error: {e}")
            transaction.status = "failed"
            transaction.save()
            return HttpResponseServerError("Could not connect to Chapa.")
    return render(request, "payments/initiate_payment_form.html")


def payment_callback_view(request):
    """Handles redirect after Chapa payment (informational only)."""
    query_status = request.GET.get("status", "").lower()
    context = {}

    if query_status in ["failed", "cancelled"]:
        context["message"] = (
            "Payment appears cancelled or failed. If you paid, wait for confirmation or contact support."
        )
        return render(request, "payments/payment_failure.html", context)
    elif query_status == "success":
        context["message"] = (
            "Payment is being processed. Confirmation will follow soon."
        )
    else:
        context["message"] = (
            "Awaiting final payment confirmation. Please check your email or order page soon."
        )

    return render(request, "payments/payment_status.html", context)


@csrf_exempt
@require_POST
def chapa_webhook_receiver(request):
    """Handles Chapa's asynchronous payment confirmation via webhook."""
    signature = request.headers.get("x-chapa-signature") or request.headers.get(
        "Chapa-Signature"
    )
    secret = getattr(settings, "CHAPA_WEBHOOK_SECRET", None)

    if not signature or not secret:
        return HttpResponseBadRequest("Missing signature or webhook secret.")

    computed_signature = hmac.new(
        secret.encode(), request.body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed_signature, signature):
        return HttpResponseBadRequest("Invalid signature.")

    try:
        data = json.loads(request.body)
        tx_ref = data.get("tx_ref")
        event = data.get("event")
        status = data.get("status")
        chapa_ref = data.get("reference")

        if not tx_ref:
            return HttpResponse("Missing transaction reference", status=200)

        transaction = PaymentTransaction.objects.get(tx_ref=tx_ref)

        if transaction.status in ["completed", "failed"]:
            return HttpResponse("Already processed", status=200)

        if event == "charge.success":
            transaction.status = "completed"
            transaction.chapa_transaction_id = (
                chapa_ref or transaction.chapa_transaction_id
            )
            transaction.save()
            # TODO: Trigger post-payment logic here
        elif event == "charge.failed" or status == "failed":
            transaction.status = "failed"
            transaction.save()
        else:
            print(f"Unhandled event type: {event} / status: {status}")

        return HttpResponse("Webhook processed", status=200)

    except PaymentTransaction.DoesNotExist:
        return HttpResponse("Transaction not found", status=200)
    except Exception as e:
        print(f"Webhook error: {e}")
        return HttpResponseServerError("Webhook processing error")
