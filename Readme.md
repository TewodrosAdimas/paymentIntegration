# Django Chapa Payment Integration (payment_project)

This is a Django project (`payment_project`) containing an app (`payments`) that demonstrates how to integrate the [Chapa Payment Gateway](https://chapa.co/) for accepting payments within a web application. It covers the essential steps:

*   Initializing a payment request.
*   Redirecting the user to the Chapa checkout page.
*   Handling the callback (`return_url`) after the user attempts payment.
*   Verifying the payment status via Chapa's API in the callback view.
*   Receiving and processing asynchronous webhook notifications for reliable payment confirmation.
*   Verifying webhook signatures for security.
*   Storing transaction details in the Django database.

**Disclaimer:** This is an example project. Ensure thorough testing, security reviews, and adherence to Chapa's latest documentation before using in a production environment.

## Features Implemented

*   **Payment Initiation (`payments/views.py:initiate_payment_view`):** Collects payment details via a simple form and requests a checkout URL from Chapa.
*   **Database Model (`payments/models.py:PaymentTransaction`):** Stores transaction details (amount, currency, status, Chapa references, tx_ref, timestamps, etc.).
*   **Callback Handling (`payments/views.py:payment_callback_view`):** Handles the user's return from Chapa, performs server-to-server verification via Chapa's Verify API, and shows a status page.
*   **Webhook Receiver (`payments/views.py:chapa_webhook_receiver`):** A secure view to listen for asynchronous payment status updates from Chapa. This is the most reliable way to confirm payment success/failure.
*   **Webhook Signature Verification:** Implements HMAC-SHA256 verification (assuming this is Chapa's method - **confirm in docs!**) using a Webhook Secret key from the Chapa dashboard.
*   **Basic Templates (`payments/templates/payments/`):** Includes simple HTML templates for the initiation form, success page, failure page, and intermediate status page.

## Requirements

*   Python 3.x
*   Django (tested with 4.x, likely compatible with others)
*   `requests` library (`pip install requests`)
*   A Chapa Developer Account ([https://dashboard.chapa.co/register](https://dashboard.chapa.co/register)) to get API keys (Secret Key and Webhook Secret).

## Setup & Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/TewodrosAdimas/paymentIntegration.git
    cd payment_project
    ```

2.  **Create and Activate Virtual Environment:**
    ```bash
    python -m venv venv
    # On Windows: venv\Scripts\activate
    # On macOS/Linux: source venv/bin/activate
    ```

3.  **Install Dependencies:**
    *(Create a `requirements.txt` file if you haven't: `pip freeze > requirements.txt`)*
    ```bash
    pip install -r requirements.txt
    # Or at least: pip install Django requests
    ```

4.  **Configure Settings (`payment_project/settings.py`):**
    *   Add the `payments` app to your `INSTALLED_APPS`:
        ```python
        INSTALLED_APPS = [
            # ... other default apps like admin, auth, etc.
            'payments', # Add your payments app here
            # ... any other apps
        ]
        ```
    *   **API Keys & Secrets:** Add your Chapa API keys and Webhook Secret. **CRITICAL: Use environment variables in production. Do NOT hardcode secrets directly in `settings.py` if avoidable.**
        ```python
        # payment_project/settings.py
        import os

        # Your Chapa SECRET key (obtained from Chapa Dashboard -> API Keys)
        # Should start with CHASECK_TEST-... or CHASECK_LIVE-...
        CHAPA_SECRET_KEY = os.environ.get('CHAPA_SECRET_KEY', 'PASTE_YOUR_CHAPA_SECRET_KEY_HERE_FOR_TESTING_ONLY')

        # Your Chapa WEBHOOK SECRET key (obtained from Chapa Dashboard -> Webhooks after creating one)
        # Used ONLY for verifying incoming webhooks.
        CHAPA_WEBHOOK_SECRET = os.environ.get('CHAPA_WEBHOOK_SECRET', 'PASTE_YOUR_CHAPA_WEBHOOK_SECRET_HERE_FOR_TESTING_ONLY')

        # Optional but Recommended: Move API URLs here too
        # CHAPA_INITIALIZE_URL = os.environ.get('CHAPA_INITIALIZE_URL', "https://api.chapa.co/v1/transaction/initialize")
        # CHAPA_VERIFY_URL = os.environ.get('CHAPA_VERIFY_URL', "https://api.chapa.co/v1/transaction/verify/") # Double-check this endpoint!
        ```
    *   Ensure your `TEMPLATES` setting includes `'APP_DIRS': True` or otherwise correctly configures the `DIRS` list to find the `payments/templates/` directory.
        ```python
        TEMPLATES = [
            {
                'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'DIRS': [], # Or [BASE_DIR / 'templates']
                'APP_DIRS': True, # Looks for templates inside app/templates/ directory
                'OPTIONS': {
                    # ... options
                },
            },
        ]
        ```

5.  **Apply Migrations:**
    ```bash
    python manage.py migrate
    ```

6.  **Include App URLs:** Ensure your main project's `urls.py` (`payment_project/urls.py`) includes the URLs from the `payments` app:
    ```python
    # payment_project/urls.py
    from django.contrib import admin
    from django.urls import path, include # Make sure include is imported

    urlpatterns = [
        path('admin/', admin.site.urls),
        # Include the URLs from the payments app, namespaced as 'payments'
        path('payments/', include('payments.urls', namespace='payments')),
        # Add other paths for your project...
    ]
    ```

7.  **Configure Chapa Dashboard:**
    *   Log in to your Chapa Dashboard.
    *   Go to **Settings -> API Keys** to find your `Secret Key` (used for `CHAPA_SECRET_KEY`).
    *   Go to **Settings -> Webhooks**.
        *   Click "**Add Webhook**".
        *   Enter your **Webhook URL**.
            *   For **local development**, you *must* use a tool like [ngrok](https://ngrok.com/) to expose your local server to the internet. If your local server runs on port 8000, run `ngrok http 8000`. Ngrok will give you a public HTTPS URL (e.g., `https://<random-string>.ngrok-free.app`). Your webhook URL will be this public URL plus your webhook path: `https://<random-string>.ngrok-free.app/payments/webhook/chapa/`
            *   For **production**, use your live domain: `https://yourdomain.com/payments/webhook/chapa/`.
        *   Choose the events you want to listen to (e.g., `charge.success`, `charge.failed`).
        *   **Save** the webhook. Chapa will then display a **Webhook Secret** key. Copy this value and use it for `CHAPA_WEBHOOK_SECRET` in your `settings.py`. This secret is ONLY used for verifying incoming webhooks and is different from your API Secret Key.

## Running the Project (Local Development)

1.  **Set Environment Variables (Recommended Method):**
    *   Open your terminal.
    *   Export the keys *before* running the server:
    ```bash
    export CHAPA_SECRET_KEY='CHASECK_TEST-...' # Paste your actual Secret Key
    export CHAPA_WEBHOOK_SECRET='whsec_...' # Paste your actual Webhook Secret
    ```
    *(Note: These variables are typically only set for the current terminal session. Use `.env` files and libraries like `python-dotenv` for a more robust approach).*

2.  **Start the Django Development Server:**
    ```bash
    python manage.py runserver # Defaults to port 8000
    # Or specify a port: python manage.py runserver 8001
    ```

3.  **Start ngrok (if testing webhooks locally):**
    *   Open *another* terminal window.
    *   Run ngrok, pointing it to the same port Django is running on:
    ```bash
    ngrok http 8000 # Or 8001 if you used a different port for runserver
    ```
    *   Copy the `https://...ngrok-free.app` URL provided by ngrok. Make sure the Webhook URL in your Chapa Dashboard points to `https://<your-ngrok-url>/payments/webhook/chapa/`.

4.  **Access the Initiation Page:** Open your browser to `http://127.0.0.1:8000/payments/initiate/` (adjust port and path based on your main `urls.py` configuration if needed).

## Payment Workflow Overview

1.  User accesses `http://.../payments/initiate/`.
2.  User fills and submits the payment form (or clicks a payment button).
3.  A `POST` request hits the `initiate_payment_view`.
4.  A `PaymentTransaction` record is created (status: `pending`).
5.  A `POST` request is sent to Chapa's Initialize API (`/v1/transaction/initialize`) containing amount, currency, user details, `tx_ref`, and the crucial `callback_url` (for the webhook) and `return_url` (for user browser redirect).
6.  If successful, Chapa responds with a `checkout_url`.
7.  Django sends an HTTP 302 Redirect, sending the user's browser to Chapa's `checkout_url`.
8.  User interacts with the Chapa payment page (enters details, authorizes payment).
9.  **Callback Phase:** After the attempt, Chapa redirects the user's browser back to the `return_url` provided during initialization (e.g., `http://.../payments/callback/?tx_ref=...&status=...`).
10. The `payment_callback_view` is triggered. It extracts the `tx_ref`.
11. It makes a server-to-server GET request to Chapa's Verify API (`/v1/transaction/verify/{tx_ref}`) using the `CHAPA_SECRET_KEY`.
12. Based on the verification response, the view renders a success/failure/pending page to give the user immediate feedback. The database *might* be updated here, but this step is less reliable than the webhook.
13. **Webhook Phase:** *Separately and asynchronously*, Chapa sends a `POST` request containing the final transaction status details to the `callback_url` provided during initialization (e.g., `http://.../payments/webhook/chapa/`).
14. The `chapa_webhook_receiver` view is triggered.
15. **Crucially**, the view verifies the `X-Chapa-Signature` header using the `CHAPA_WEBHOOK_SECRET`.
16. If the signature is valid, the JSON payload is parsed.
17. The corresponding `PaymentTransaction` record is reliably updated (e.g., to `completed` or `failed`).
18. **Reliable post-payment actions (activating services, marking orders paid, sending confirmation emails) should be triggered HERE, within the verified webhook handler.**
19. A `200 OK` HTTP response is sent back to Chapa to acknowledge receipt of the webhook.
