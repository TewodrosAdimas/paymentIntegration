# payments/views.py
import requests
import json
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    JsonResponse, HttpResponseBadRequest, HttpResponseServerError, HttpResponse
)
from django.urls import reverse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import PaymentTransaction
import hmac
import hashlib # For webhook verification (assuming HMAC-SHA256, CONFIRM with Chapa)


# --- Chapa API Configuration ---
# !! Double-check these URLs in your Chapa developer dashboard !!
CHAPA_INITIALIZE_URL = "https://api.chapa.co/v1/transaction/initialize"
# !! CRITICAL: Verify if this should be /transaction/verify/ OR /transfers/verify/ for customer payments !!
# !! Based on standard patterns, /transaction/verify/ is more likely for verifying initated transactions !!
CHAPA_VERIFY_URL = "https://api.chapa.co/v1/transaction/verify/" # Using transaction verify endpoint


# --- Views ---

def initiate_payment_view(request):
    if request.method == 'POST':
        # --- Get data from your form or context ---
        # Ensure you validate this data properly in a real application
        amount_str = request.POST.get('amount', '10.00') # Example
        email = request.POST.get('email', 'test@example.com') # Example
        first_name = request.POST.get('first_name', 'Test')
        last_name = request.POST.get('last_name', 'User')
        phone_number = request.POST.get('phone_number', '0911111111') # Example
        currency = 'ETB'
        # --- ---

        # 1. Generate your unique transaction reference
        # Using a prefix + uuid ensures more uniqueness if needed
        tx_ref = f"tx_{uuid.uuid4().hex[:16]}"

        # 2. Create a PaymentTransaction record in 'pending' state
        try:
            # Ensure amount is valid Decimal before saving
            from decimal import Decimal, InvalidOperation
            try:
                amount_decimal = Decimal(amount_str)
            except InvalidOperation:
                 print(f"Invalid amount format: {amount_str}")
                 return HttpResponseBadRequest("Invalid amount format.")

            transaction = PaymentTransaction.objects.create(
                tx_ref=tx_ref,
                amount=amount_decimal,
                currency=currency,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number, # Save phone number
                status='pending'
                # Add user/order links if needed
            )
        except Exception as e:
             print(f"Error creating transaction record: {e}")
             return HttpResponseServerError("Error recording transaction.")

        # 3. Prepare data for Chapa API Initialization
        headers = {
            'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
            'Content-Type': 'application/json',
        }

        # !! Construct absolute URLs correctly !!
        # Use request.build_absolute_uri for development and configure domain properly for production
        callback_url = request.build_absolute_uri(reverse('payments:chapa_webhook'))
        return_url = request.build_absolute_uri(reverse('payments:payment_callback'))

        payload = {
            "amount": amount_str, # Chapa expects amount as string according to example
            "currency": currency,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number, # Include phone number
            "tx_ref": tx_ref,
            "callback_url": callback_url, # For Webhook notifications
            "return_url": return_url,    # For user browser redirect after payment attempt
            "customization[title]": "Payment for My Awesome Service", # Use dict or flat keys based on docs
            "customization[description]": f"Order Ref: {tx_ref}"
        }
        # Alternative customization format if Chapa expects nested dict:
        # payload["customization"] = {
        #     "title": "Payment for My Awesome Service",
        #     "description": f"Order Ref: {tx_ref}"
        # }
        # Use the format shown in the documentation you have. The flat key format is common.

        print(f"Chapa Init Payload: {payload}") # Debugging
        print(f"Chapa Init Headers: {headers}") # Debugging

        # 4. Make the API call to Chapa using requests library
        try:
            # Use json=payload - requests handles JSON encoding and Content-Type
            response = requests.post(CHAPA_INITIALIZE_URL, headers=headers, json=payload, timeout=15)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            response_data = response.json()
            print(f"Chapa Init Response: {response_data}") # Debugging

            # 5. Process the Chapa response
            if response_data.get('status') == 'success':
                checkout_url = response_data.get('data', {}).get('checkout_url')
                if checkout_url:
                    # Redirect user to Chapa's payment page
                    return redirect(checkout_url)
                else:
                     print(f"Error: Checkout URL not found in Chapa response. Data: {response_data}")
                     # Update transaction status?
                     # transaction.status = 'failed'
                     # transaction.save()
                     return HttpResponseServerError("Could not initiate payment (missing checkout URL).")
            else:
                # Log the error details from Chapa
                print(f"Error: Chapa initialization failed. Status: {response_data.get('status')}, Message: {response_data.get('message')}, Data: {response_data}")
                # Update transaction status?
                # transaction.status = 'failed'
                # transaction.save()
                return HttpResponseServerError(f"Could not initiate payment: {response_data.get('message', 'Unknown error')}")

        except requests.exceptions.Timeout:
            print(f"Error: Timeout calling Chapa Initialize API for {tx_ref}")
            # Update transaction status? Consider 'pending' or a specific 'timeout' status
            return HttpResponseServerError("Payment gateway timeout.")
        except requests.exceptions.RequestException as e:
            # Handle network errors, invalid URL, etc.
            print(f"Error calling Chapa Initialize API: {e}")
            # Update transaction status?
            # transaction.status = 'failed'
            # transaction.save()
            return HttpResponseServerError("Could not connect to payment gateway.")
        except Exception as e:
            # Handle other unexpected errors (JSON decoding, etc.)
            print(f"Unexpected error during payment initiation for {tx_ref}: {e}")
            # transaction.status = 'failed' # Or requires manual review
            # transaction.save()
            return HttpResponseServerError("An unexpected error occurred.")

    # If GET request, show a simple form (or integrate into your checkout page)
    return render(request, 'payments/initiate_payment_form.html') # Create this template


def payment_callback_view(request):
    """
    Handles the redirect back from Chapa after the user attempts payment.
    Verifies the transaction status via a server-to-server API call.
    """
    # Chapa usually appends tx_ref as query param to the return_url
    tx_ref = request.GET.get('tx_ref')
    # Sometimes status is also included, but DO NOT rely on it for confirmation
    # query_status = request.GET.get('status')

    if not tx_ref:
        print("Callback Error: Missing tx_ref in query parameters.")
        return HttpResponseBadRequest("Missing transaction reference.")

    print(f"Callback received for tx_ref: {tx_ref}")

    try:
        transaction = get_object_or_404(PaymentTransaction, tx_ref=tx_ref)

        # Prevent re-processing if already completed/failed via webhook or previous callback
        if transaction.status in ['completed', 'failed']:
             print(f"Transaction {tx_ref} already processed with status: {transaction.status}. Showing status page.")
             # Redirect to a page showing final status
             if transaction.status == 'completed':
                 return render(request, 'payments/payment_success.html', {'transaction': transaction})
             else:
                 return render(request, 'payments/payment_failure.html', {'transaction': transaction})

        # 1. Call Chapa's Verification Endpoint (**CONFIRM THE ENDPOINT URL**)
        headers = {
            'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
        }
        # Construct the correct verification URL based on confirmed endpoint
        verify_url = f"{CHAPA_VERIFY_URL}{tx_ref}" # Assumes /transaction/verify/ endpoint

        print(f"Verifying transaction {tx_ref} at URL: {verify_url}")

        try:
            response = requests.get(verify_url, headers=headers, timeout=10)
            response.raise_for_status() # Raise HTTPError for 4xx/5xx status codes
            verify_data = response.json()
            print(f"Chapa Verify Response for {tx_ref}: {verify_data}")

            # 2. Check the verification response status
            # Check Chapa docs for the exact structure and status values
            if verify_data.get('status') == 'success':
                # Find the actual transaction status within the 'data' object
                chapa_tx_status = verify_data.get('data', {}).get('status')

                if chapa_tx_status == 'success': # Or the specific status Chapa uses for successful payment
                    transaction.status = 'completed'
                    # Store Chapa's own reference ID if available and useful
                    transaction.chapa_transaction_id = verify_data.get('data', {}).get('reference') # Adjust field name if needed
                    transaction.save()
                    print(f"Payment successful for tx_ref: {tx_ref} (via callback verification)")
                    # Trigger post-payment actions (e.g., update order, send email)
                    # Be mindful of doing this here AND in the webhook - use flags to prevent duplication
                    # E.g., add a boolean field `fulfillment_triggered` to the model
                    return render(request, 'payments/payment_success.html', {'transaction': transaction})
                else:
                    # Payment failed or is still pending according to Chapa verification
                    transaction.status = 'failed' # Or map Chapa status appropriately ('pending', 'cancelled' etc.)
                    transaction.save()
                    print(f"Payment verification check failed for {tx_ref}. Chapa status: {chapa_tx_status}")
                    return render(request, 'payments/payment_failure.html', {'transaction': transaction, 'chapa_status': chapa_tx_status})
            else:
                # Verification API call itself reported an issue (e.g., "failed" status in outer object)
                transaction.status = 'failed' # Mark as failed if verification itself fails
                transaction.save()
                print(f"Chapa verification API call failed for {tx_ref}. Response: {verify_data}")
                return render(request, 'payments/payment_failure.html', {'message': 'Could not verify payment status.', 'transaction': transaction})

        except requests.exceptions.Timeout:
            print(f"Error: Timeout verifying transaction {tx_ref}")
            # Don't change status definitively yet, rely on webhook or retry later
            # Show a user-friendly message
            return render(request, 'payments/payment_status.html', {'message': 'Verification timed out. We will update the status shortly or contact support.', 'transaction': transaction})
        except requests.exceptions.RequestException as e:
            # Network error or non-2xx status code during verification
            print(f"Error verifying transaction {tx_ref}: {e}. Response status: {e.response.status_code if e.response else 'N/A'}")
            # Don't change status definitively yet
            return render(request, 'payments/payment_status.html', {'message': 'Could not verify payment status at this time. Please check back later or contact support.', 'transaction': transaction})
        except Exception as e:
             print(f"Unexpected error during payment verification for {tx_ref}: {e}")
             # Consider marking as requires_manual_review or failed
             return render(request, 'payments/payment_status.html', {'message': 'An unexpected error occurred during verification.', 'transaction': transaction})

    except PaymentTransaction.DoesNotExist:
        print(f"Callback Error: Transaction with tx_ref {tx_ref} not found.")
        return HttpResponseBadRequest("Invalid transaction reference.")
    except Exception as e:
         print(f"General error in callback view for {tx_ref}: {e}")
         return HttpResponseServerError("An error occurred processing the payment callback.")


@csrf_exempt # Disable CSRF protection for webhook endpoint
@require_POST # Ensure only POST requests are accepted
def chapa_webhook_receiver(request):
    """
    Handles asynchronous notifications (webhooks) from Chapa.
    This is the MOST RELIABLE way to confirm final transaction status.
    """
    # --- 1. Verify the webhook signature (CRITICAL SECURITY STEP) ---
    # !!! YOU MUST find Chapa's documentation for webhook security !!!
    # !!! What is the header name? (e.g., 'X-Chapa-Signature', 'Webhook-Signature') !!!
    # !!! What is the algorithm? (e.g., HMAC-SHA256) !!!
    # !!! You need a Webhook Secret key from your Chapa dashboard !!!

    chapa_signature_header = "X-Chapa-Signature" # !! REPLACE with actual header name from Chapa Docs !!
    signature = request.headers.get(chapa_signature_header)
    webhook_secret = settings.CHAPA_WEBHOOK_SECRET

    if not signature:
        print("Webhook Error: Missing signature header.")
        return HttpResponseBadRequest(f'Missing {chapa_signature_header} header.')
    if not webhook_secret:
        print("Webhook Error: Webhook secret is not configured in settings.")
        # Don't reveal secret absence to the outside world in production
        return HttpResponseBadRequest('Webhook configuration error.')

    try:
        # Example verification assuming HMAC-SHA256 (!! ADAPT TO CHAPA'S METHOD !!)
        computed_hash = hmac.new(
            webhook_secret.encode('utf-8'),
            request.body, # Use the raw request body
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, signature):
             print(f"Webhook Error: Invalid signature. Received: {signature}, Computed: {computed_hash}")
             return HttpResponseBadRequest('Invalid signature.')
        else:
            print("Webhook signature verified successfully.")

    except Exception as e:
        print(f"Webhook Error: Exception during signature verification: {e}")
        return HttpResponseBadRequest('Signature verification error.')

    # --- 2. Parse the incoming JSON data ---
    try:
        event_data = json.loads(request.body)
        print(f"Received Verified Chapa Webhook: {json.dumps(event_data, indent=2)}") # Log formatted JSON
    except json.JSONDecodeError:
         print("Webhook Error: Invalid JSON payload.")
         return HttpResponseBadRequest('Invalid JSON payload.')

    # --- 3. Process the event data ---
    # Check Chapa docs for the payload structure (event type field, status field, tx_ref field)
    event_type = event_data.get('event') # Example field name
    tx_ref = event_data.get('tx_ref') # Example field name
    event_status = event_data.get('status') # Example field name (might be nested)

    # Try finding tx_ref in common nested locations if not top-level
    if not tx_ref and isinstance(event_data.get('data'), dict):
        tx_ref = event_data.get('data', {}).get('tx_ref')

    if not tx_ref:
        print("Webhook Error: Missing tx_ref in payload.")
        # Still return 200 OK to prevent Chapa retries for a payload we can't process
        return HttpResponse('Missing transaction reference', status=200)

    try:
        transaction = PaymentTransaction.objects.get(tx_ref=tx_ref)

        # Idempotency: Check if already processed to final state
        if transaction.status in ['completed', 'failed']:
             print(f"Webhook Info: Transaction {tx_ref} already in final state {transaction.status}. Ignoring event '{event_type or event_status}'.")
             return HttpResponse(status=200) # Acknowledge receipt

        # Determine outcome based on event type or status from Chapa's payload
        # !! Adjust these conditions based on actual Chapa webhook payload structure !!
        is_success = event_type == 'charge.success' or event_status == 'success' # Example success conditions
        is_failure = event_type == 'charge.failed' or event_status == 'failed' # Example failure conditions

        if is_success:
            transaction.status = 'completed'
            # Optionally grab Chapa's transaction ID from webhook data if needed
            if isinstance(event_data.get('data'), dict):
                transaction.chapa_transaction_id = event_data.get('data', {}).get('reference', transaction.chapa_transaction_id)
            transaction.save()
            print(f"Webhook: Updated transaction {tx_ref} to COMPLETED.")
            # --- Trigger reliable post-payment actions HERE ---
            # - Mark order as paid
            # - Send confirmation email
            # - Start fulfillment process
            # Add logic to ensure this runs only once (e.g., check a `fulfillment_triggered` flag)
            # ---------------------------------------------------

        elif is_failure:
            transaction.status = 'failed'
            transaction.save()
            print(f"Webhook: Updated transaction {tx_ref} to FAILED.")
            # Handle failure (notify admin? update user?)

        else:
            # Log unhandled event types/statuses for debugging
            print(f"Webhook Info: Received unhandled event/status for {tx_ref}. Event: '{event_type}', Status: '{event_status}'")
            # Don't change status if unsure

        # 4. Return a 200 OK response to Chapa quickly
        return HttpResponse(status=200)

    except PaymentTransaction.DoesNotExist:
         print(f"Webhook Warning: Transaction with tx_ref {tx_ref} not found.")
         # Return 200 OK so Chapa doesn't keep retrying for a transaction we don't know about
         return HttpResponse('Transaction not found', status=200)
    except Exception as e:
         print(f"Webhook Error: Error processing webhook for {tx_ref}: {e}")
         # Return 500 to signal an error processing, Chapa might retry
         return HttpResponseServerError("Webhook processing error")