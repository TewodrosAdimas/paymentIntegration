import requests # If using requests library
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseServerError, HttpResponse
from django.urls import reverse
from django.conf import settings
from .models import PaymentTransaction
import uuid # For generating tx_ref if not done in model default

# Replace with actual Chapa API endpoint from their documentation
CHAPA_INITIALIZE_URL = "https://api.chapa.co/v1/transaction/initialize"
CHAPA_VERIFY_URL = "https://api.chapa.co/v1/transaction/verify/" # Note trailing slash usually needed

def initiate_payment_view(request):
    if request.method == 'POST':
        # Ideally get amount, email etc. from a form or context (e.g., cart total)
        amount = request.POST.get('amount', '100.00') # Example amount
        email = request.POST.get('email', 'test@example.com') # Example email
        first_name = request.POST.get('first_name', 'Test')
        last_name = request.POST.get('last_name', 'User')
        currency = 'ETB' # Chapa primarily uses ETB

        # 1. Generate your unique transaction reference
        tx_ref = f"tx_{uuid.uuid4().hex[:12]}" # Example unique ref

        # 2. Create a PaymentTransaction record in 'pending' state
        try:
            transaction = PaymentTransaction.objects.create(
                tx_ref=tx_ref,
                amount=amount,
                currency=currency,
                email=email,
                first_name=first_name,
                last_name=last_name,
                status='pending'
                # Add user/order links if needed
            )
        except Exception as e:
             # Log the error
             print(f"Error creating transaction record: {e}")
             return HttpResponseServerError("Error recording transaction.")


        # 3. Prepare data for Chapa API
        headers = {
            'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
            'Content-Type': 'application/json',
        }
        # Construct the callback URL dynamically
        # Ensure your domain/protocol are correct, especially in production
        return_url = request.build_absolute_uri(reverse('payments:payment_callback'))

        payload = {
            "amount": str(amount), # Ensure it's a string if API requires
            "currency": currency,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "tx_ref": tx_ref,
            "callback_url": return_url, # URL Chapa redirects to after payment attempt
            "return_url": return_url, # Often the same, check Chapa docs
            # Add any other required/optional fields from Chapa docs (e.g., phone_number, title, description)
            "customization[title]": "Payment for My Awesome Service",
            "customization[description]": f"Order Ref: {tx_ref}"
        }

        # 4. Make the API call to Chapa
        try:
            response = requests.post(CHAPA_INITIALIZE_URL, headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            response_data = response.json()

            # 5. Process the response
            if response_data.get('status') == 'success':
                checkout_url = response_data.get('data', {}).get('checkout_url')
                if checkout_url:
                    # Store raw response for debugging? (optional)
                    # transaction.raw_initiation_response = response_data
                    # transaction.save()
                    # Redirect user to Chapa's payment page
                    return redirect(checkout_url)
                else:
                     print(f"Error: Checkout URL not found in Chapa response. Data: {response_data}")
                     return HttpResponseServerError("Could not initiate payment (missing checkout URL).")
            else:
                # Log the error details from Chapa
                print(f"Error: Chapa initialization failed. Status: {response_data.get('status')}, Message: {response_data.get('message')}, Data: {response_data}")
                return HttpResponseServerError(f"Could not initiate payment: {response_data.get('message', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            # Handle network errors, timeouts, etc.
            print(f"Error calling Chapa API: {e}")
            return HttpResponseServerError("Could not connect to payment gateway.")
        except Exception as e:
            # Handle other unexpected errors (JSON decoding, etc.)
            print(f"Unexpected error during payment initiation: {e}")
            return HttpResponseServerError("An unexpected error occurred.")

    # If GET request, show a simple form (or integrate into your checkout page)
    return render(request, 'payments/initiate_payment_form.html') # Create this template