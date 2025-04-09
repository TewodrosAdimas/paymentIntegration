# payments/views.py
import requests
import json # Import json for formatted printing
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
# !! Move these to settings.py for better practice !!
CHAPA_INITIALIZE_URL = getattr(settings, 'CHAPA_INITIALIZE_URL', "https://api.chapa.co/v1/transaction/initialize")
CHAPA_VERIFY_URL = getattr(settings, 'CHAPA_VERIFY_URL', "https://api.chapa.co/v1/transaction/verify/") # Confirm this endpoint


# --- Views ---

def initiate_payment_view(request):
    if request.method == 'POST':
        # --- Get data from your form or context ---
        # TODO: Use Django Forms for robust validation here
        amount_str = request.POST.get('amount', '10.00') # Example
        email = request.POST.get('email', 'test@example.com') # Example
        first_name = request.POST.get('first_name', 'Test')
        last_name = request.POST.get('last_name', 'User')
        phone_number = request.POST.get('phone_number', '0911111111') # Example
        currency = 'ETB'
        # --- ---

        # 1. Generate your unique transaction reference
        tx_ref = f"tx_{uuid.uuid4().hex[:16]}"

        # 2. Create a PaymentTransaction record in 'pending' state
        try:
            from decimal import Decimal, InvalidOperation
            try:
                amount_decimal = Decimal(amount_str)
                # Add basic validation for amount > 0 if needed
                if amount_decimal <= 0:
                    print(f"Invalid amount: {amount_str}. Must be positive.")
                    return HttpResponseBadRequest("Invalid amount: Must be positive.")
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
                phone_number=phone_number,
                status='pending'
                # Add user/order links if needed
            )
        except Exception as e:
             # Use Django logging in production
             print(f"Error creating transaction record: {e}")
             return HttpResponseServerError("Error recording transaction.")

        # 3. Prepare data for Chapa API Initialization
        headers = {
            # Ensure settings.CHAPA_SECRET_KEY is correctly configured
            'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
            'Content-Type': 'application/json',
        }

        try:
            callback_url = request.build_absolute_uri(reverse('payments:chapa_webhook'))
            return_url = request.build_absolute_uri(reverse('payments:payment_callback'))
        except Exception as e:
             print(f"Error building absolute URIs: {e}")
             return HttpResponseServerError("Error configuring redirect URLs.")

        # --- MODIFICATION START ---
        # Structure 'customization' as a nested dictionary for JSON payload
        payload = {
            "amount": amount_str,
            "currency": currency,
            "email": email, # Keep 'test@example.com' for now, change if error persists
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
            "tx_ref": tx_ref,
            "callback_url": callback_url,
            "return_url": return_url,
            "customization": {
                # Shorten title to 16 chars or less
                "title": "Awesome Payment", # Example: Changed title
                # Remove the colon, ensure only allowed characters
                "description": f"OrderRef {tx_ref}" # Example: Removed colon
            }
        }

        # Use json.dumps for clearer debugging output of the actual JSON sent
        print(f"Chapa Init Payload: {json.dumps(payload, indent=2)}")
        print(f"Chapa Init Headers: {headers}")

        # 4. Make the API call to Chapa using requests library
        try:
            # Use json=payload - requests handles JSON encoding and Content-Type
            response = requests.post(CHAPA_INITIALIZE_URL, headers=headers, json=payload, timeout=15)

            # Check for specific 4xx/5xx errors BEFORE raise_for_status
            # to potentially get more details from the response body
            if not response.ok: # Catches 4xx and 5xx status codes
                error_details = response.text # Get raw text response
                try:
                    # Try to parse JSON error response from Chapa if available
                    error_json = response.json()
                    print(f"Chapa Init Error Response JSON: {error_json}")
                    error_message = error_json.get('message', response.reason) # Get Chapa's message if possible
                except json.JSONDecodeError:
                    # If response is not JSON, use the raw text
                    print(f"Chapa Init Error Response Text: {error_details}")
                    error_message = response.reason # Default HTTP reason phrase

                # Raise the exception *after* logging details
                response.raise_for_status()

            # If response.ok is True, proceed
            response_data = response.json()
            print(f"Chapa Init Response: {response_data}")

            # 5. Process the Chapa success response
            if response_data.get('status') == 'success':
                checkout_url = response_data.get('data', {}).get('checkout_url')
                if checkout_url:
                    # Redirect user to Chapa's payment page
                    return redirect(checkout_url)
                else:
                     print(f"Error: Checkout URL not found in Chapa success response. Data: {response_data}")
                     transaction.status = 'failed' # Mark as failed if URL missing
                     transaction.save()
                     return HttpResponseServerError("Could not initiate payment (missing checkout URL).")
            else:
                # Log the error details from Chapa even if status is not 'success' (unlikely if raise_for_status didn't trigger)
                print(f"Error: Chapa initialization status not 'success'. Status: {response_data.get('status')}, Message: {response_data.get('message')}")
                transaction.status = 'failed' # Mark as failed
                transaction.save()
                return HttpResponseServerError(f"Could not initiate payment: {response_data.get('message', 'Unknown error')}")

        except requests.exceptions.HTTPError as e:
            # Error already logged above if response.ok was False
            # Handle specific status codes if needed (e.g., 400 Bad Request vs 5xx Server Error)
            print(f"HTTP Error during Chapa Initialize API call for {tx_ref}: {e}")
            transaction.status = 'failed' # Mark as failed on HTTP error
            transaction.save()
            # Pass a more informative error message if available from the logging above
            return HttpResponseServerError(f"Payment gateway rejected the request ({e.response.status_code}). Check server logs for details.")

        except requests.exceptions.Timeout:
            print(f"Error: Timeout calling Chapa Initialize API for {tx_ref}")
            # Status remains 'pending', might succeed later or need manual check
            return HttpResponseServerError("Payment gateway timeout. Please try again later.")
        except requests.exceptions.RequestException as e:
            # Handle network errors, invalid URL, DNS issues etc.
            print(f"Error calling Chapa Initialize API (Network/Connection): {e}")
            # Status remains 'pending'
            return HttpResponseServerError("Could not connect to payment gateway. Check network connection.")
        except Exception as e:
            # Handle other unexpected errors (JSON decoding of SUCCESS response, etc.)
            print(f"Unexpected error during payment initiation for {tx_ref}: {e}")
            transaction.status = 'failed' # Mark as failed for safety
            transaction.save()
            return HttpResponseServerError("An unexpected error occurred during payment initiation.")

    # If GET request, show a simple form (or integrate into your checkout page)
    return render(request, 'payments/initiate_payment_form.html')


def payment_callback_view(request):
    """
    Handles the redirect back from Chapa after the user attempts payment.
    Verifies the transaction status via a server-to-server API call.
    This provides immediate feedback but webhook is more reliable.
    """
    tx_ref = request.GET.get('tx_ref')
    query_status = request.GET.get('status') # Check if Chapa sends status, but DO NOT TRUST IT

    print(f"Callback received for tx_ref: {tx_ref}, Query Status: {query_status}")

    if not tx_ref:
        print("Callback Error: Missing tx_ref in query parameters.")
        return HttpResponseBadRequest("Missing transaction reference.")

    try:
        # Use select_for_update to lock the row during processing if needed,
        # though webhook idempotency check is usually sufficient.
        transaction = get_object_or_404(PaymentTransaction, tx_ref=tx_ref)

        # Idempotency: Prevent re-processing or showing wrong status if webhook already ran
        if transaction.status == 'completed':
             print(f"Transaction {tx_ref} already completed. Showing success page.")
             return render(request, 'payments/payment_success.html', {'transaction': transaction})
        if transaction.status == 'failed':
             print(f"Transaction {tx_ref} already failed. Showing failure page.")
             return render(request, 'payments/payment_failure.html', {'transaction': transaction})

        # If status is still 'pending', proceed with verification
        print(f"Transaction {tx_ref} is pending. Attempting verification via API.")

        # 1. Call Chapa's Verification Endpoint
        headers = {
            'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
        }
        verify_url = f"{CHAPA_VERIFY_URL}{tx_ref}" # Assumes /transaction/verify/ endpoint

        print(f"Verifying transaction {tx_ref} at URL: {verify_url}")

        try:
            response = requests.get(verify_url, headers=headers, timeout=10)

            # Log details even on error before raising
            if not response.ok:
                error_details = response.text
                try:
                    error_json = response.json()
                    print(f"Chapa Verify Error Response JSON: {error_json}")
                except json.JSONDecodeError:
                    print(f"Chapa Verify Error Response Text: {error_details}")
                response.raise_for_status() # Raise HTTPError

            verify_data = response.json()
            print(f"Chapa Verify Response for {tx_ref}: {json.dumps(verify_data, indent=2)}")

            # 2. Check the verification response status
            if verify_data.get('status') == 'success' and isinstance(verify_data.get('data'), dict):
                chapa_tx_status = verify_data['data'].get('status')
                print(f"Chapa verification API reports internal status: {chapa_tx_status}")

                # Check Chapa docs for exact success status string(s)
                if chapa_tx_status == 'success':
                    # Double-check current status before saving to avoid race conditions with webhook
                    if transaction.status == 'pending':
                        transaction.status = 'completed'
                        transaction.chapa_transaction_id = verify_data['data'].get('reference') # Adjust field name if needed
                        transaction.save()
                        print(f"Payment successful for tx_ref: {tx_ref} (via callback verification)")
                        # DO NOT trigger critical fulfillment here. Rely on webhook.
                    # Render success page regardless if Chapa says success
                    return render(request, 'payments/payment_success.html', {'transaction': transaction})
                else:
                    # Payment failed or is still pending according to Chapa verification
                    # Only update to 'failed' if not already completed by a concurrent webhook
                    if transaction.status == 'pending':
                        # Consider mapping Chapa statuses ('pending', 'cancelled', etc.) if available
                        transaction.status = 'failed'
                        transaction.save()
                        print(f"Payment verification check failed for {tx_ref}. Chapa status: {chapa_tx_status}. Marked as failed.")
                    # Render failure page
                    return render(request, 'payments/payment_failure.html', {'transaction': transaction, 'chapa_status': chapa_tx_status})
            else:
                # Verification API call structure was unexpected or outer status wasn't success
                print(f"Chapa verification API call response format issue or outer status not 'success' for {tx_ref}. Response: {verify_data}")
                if transaction.status == 'pending':
                     transaction.status = 'failed' # Mark as failed if verification response is problematic
                     transaction.save()
                return render(request, 'payments/payment_failure.html', {'message': 'Could not reliably verify payment status.', 'transaction': transaction})

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error verifying transaction {tx_ref}: {e}. Status Code: {e.response.status_code if e.response else 'N/A'}")
            # Don't change status definitively yet, could be temporary API issue. Rely on webhook.
            # Show an intermediate/error page to the user
            return render(request, 'payments/payment_status.html', {'message': f'Verification failed ({e.response.status_code}). We will update the status via webhook or contact support.', 'transaction': transaction})
        except requests.exceptions.Timeout:
            print(f"Error: Timeout verifying transaction {tx_ref}")
            # Show an intermediate page
            return render(request, 'payments/payment_status.html', {'message': 'Verification timed out. We will update the status shortly or contact support.', 'transaction': transaction})
        except requests.exceptions.RequestException as e:
            # Network error during verification
            print(f"Error verifying transaction {tx_ref} (Network/Connection): {e}")
            # Show an intermediate page
            return render(request, 'payments/payment_status.html', {'message': 'Could not connect to verify payment status at this time. Please check back later or contact support.', 'transaction': transaction})
        except Exception as e:
             print(f"Unexpected error during payment verification for {tx_ref}: {e}")
             # Show an intermediate page - avoid setting to failed unless sure
             return render(request, 'payments/payment_status.html', {'message': 'An unexpected error occurred during verification.', 'transaction': transaction})

    except PaymentTransaction.DoesNotExist:
        print(f"Callback Error: Transaction with tx_ref {tx_ref} not found.")
        return HttpResponseBadRequest("Invalid transaction reference.")
    except Exception as e:
         # Catch-all for errors like DB connection issues before verification
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
    # !!! CONFIRM THESE DETAILS WITH CHAPA DOCUMENTATION !!!
    chapa_signature_header = "X-Chapa-Signature" # !! REPLACE with actual header name !!
    signature = request.headers.get(chapa_signature_header)
    # Ensure settings.CHAPA_WEBHOOK_SECRET is set correctly
    webhook_secret = getattr(settings, 'CHAPA_WEBHOOK_SECRET', None)

    if not signature:
        print("Webhook Error: Missing signature header.")
        # Return 400 Bad Request - client error
        return HttpResponseBadRequest(f'Missing {chapa_signature_header} header.')
    if not webhook_secret:
        print("Webhook Error: Webhook secret is not configured in settings.")
        # Return 500 Server Error - internal configuration problem
        # Avoid revealing specific config issues in production if possible
        return HttpResponseServerError('Webhook configuration error.')

    try:
        # Assumes HMAC-SHA256 - !! CONFIRM ALGORITHM WITH CHAPA DOCS !!
        computed_hash = hmac.new(
            webhook_secret.encode('utf-8'),
            request.body, # Use the raw request body
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, signature):
             print(f"Webhook Error: Invalid signature. Received: {signature}, Computed: {computed_hash}")
             # Return 400 Bad Request - invalid signature provided by caller
             return HttpResponseBadRequest('Invalid signature.')
        else:
            print("Webhook signature verified successfully.")

    except Exception as e:
        print(f"Webhook Error: Exception during signature verification: {e}")
        # Return 500 Server Error - problem during verification process
        return HttpResponseServerError('Signature verification error.')

    # --- 2. Parse the incoming JSON data ---
    try:
        event_data = json.loads(request.body)
        # Log the full payload for debugging (consider sampling/limiting in production)
        print(f"Received Verified Chapa Webhook: {json.dumps(event_data, indent=2)}")
    except json.JSONDecodeError:
         print("Webhook Error: Invalid JSON payload.")
         # Return 400 Bad Request - malformed payload from caller
         return HttpResponseBadRequest('Invalid JSON payload.')

    # --- 3. Process the event data ---
    # !! Adjust field names based on actual Chapa webhook payload structure !!
    event_type = event_data.get('event') # e.g., 'charge.success'
    tx_ref = event_data.get('tx_ref')
    event_status = event_data.get('status') # e.g., 'success' (might be top-level or nested)
    data_payload = event_data.get('data') # Often details are inside a 'data' object

    # Try finding tx_ref in common nested locations if not top-level
    if not tx_ref and isinstance(data_payload, dict):
        tx_ref = data_payload.get('tx_ref')
    # Also check if the primary status is nested
    if not event_status and isinstance(data_payload, dict):
        event_status = data_payload.get('status')

    if not tx_ref:
        print("Webhook Error: Missing tx_ref in payload.")
        # We verified signature, but can't process payload. Return 200 OK to Chapa
        # to acknowledge receipt and prevent retries for this unprocessable event.
        return HttpResponse('Webhook received but missing transaction reference.', status=200)

    try:
        # Use select_for_update to prevent race conditions if multiple webhooks arrive close together
        # Requires a database transaction
        # from django.db import transaction as db_transaction
        # with db_transaction.atomic():
        #    transaction = PaymentTransaction.objects.select_for_update().get(tx_ref=tx_ref)

        # Simpler approach without select_for_update relies on status check below
        transaction = PaymentTransaction.objects.get(tx_ref=tx_ref)

        # Idempotency: Check if already processed to final state
        if transaction.status in ['completed', 'failed']:
             print(f"Webhook Info: Transaction {tx_ref} already in final state '{transaction.status}'. Ignoring event '{event_type or event_status}'.")
             return HttpResponse(f"Transaction already {transaction.status}", status=200) # Acknowledge receipt

        # Determine outcome based on event type or status from Chapa's payload
        # !! Refine these conditions based on actual Chapa webhook payload structure !!
        # Prioritize event type if available, otherwise use status.
        is_success = event_type == 'charge.success' or (not event_type and event_status == 'success')
        is_failure = event_type == 'charge.failed' or (not event_type and event_status == 'failed') # Add other failure statuses if needed

        if is_success:
            transaction.status = 'completed'
            # Optionally grab Chapa's transaction ID from webhook data if needed and not already set
            if not transaction.chapa_transaction_id and isinstance(data_payload, dict):
                transaction.chapa_transaction_id = data_payload.get('reference', transaction.chapa_transaction_id)
            transaction.save()
            print(f"Webhook: Updated transaction {tx_ref} to COMPLETED.")

            # --- Trigger reliable post-payment actions HERE ---
            try:
                # Example: Add a flag 'fulfillment_triggered' to PaymentTransaction model
                # if not transaction.fulfillment_triggered:
                #    trigger_order_fulfillment(transaction.order) # Assuming linked order
                #    send_payment_confirmation_email(transaction)
                #    transaction.fulfillment_triggered = True
                #    transaction.save(update_fields=['fulfillment_triggered'])
                print(f"Webhook: Post-payment actions for {tx_ref} should be triggered here.")
                pass # Replace with your actual fulfillment logic
            except Exception as post_payment_error:
                 print(f"Webhook CRITICAL ERROR: Failed to trigger post-payment actions for {tx_ref}: {post_payment_error}")
                 # Log this critical error for manual intervention
            # ---------------------------------------------------

        elif is_failure:
            transaction.status = 'failed'
            transaction.save()
            print(f"Webhook: Updated transaction {tx_ref} to FAILED.")
            # Handle failure (notify admin? update user UI? cancel order?)
            print(f"Webhook: Post-failure actions for {tx_ref} could be triggered here.")
            pass

        else:
            # Log unhandled event types/statuses for debugging
            print(f"Webhook Info: Received unhandled/intermediate event/status for {tx_ref}. Event: '{event_type}', Status: '{event_status}'. No status change.")
            # Don't change status if unsure (e.g., 'pending', 'processing' events)

        # 4. Return a 200 OK response to Chapa quickly to acknowledge receipt
        return HttpResponse("Webhook processed successfully", status=200)

    except PaymentTransaction.DoesNotExist:
         print(f"Webhook Warning: Transaction with tx_ref {tx_ref} not found in DB.")
         # Return 200 OK so Chapa doesn't keep retrying for a transaction we don't know about
         return HttpResponse('Transaction not found', status=200)
    except Exception as e:
         print(f"Webhook Error: Error processing webhook payload for {tx_ref}: {e}")
         # Return 500 to signal an internal server error processing this valid webhook, Chapa might retry
         return HttpResponseServerError("Internal server error processing webhook")