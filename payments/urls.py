# payments/urls.py

from django.urls import path
from django.shortcuts import render # For simple template rendering if needed
from . import views

# Define a namespace for URL reversing (e.g., {% url 'payments:initiate_payment' %})
app_name = 'payments'

urlpatterns = [
    # URL to display the form/button that starts the payment process
    # (Calls initiate_payment_view on POST)
    path('', views.initiate_payment_view, name='initiate_payment'),

    # URL the user is redirected back to by Chapa after attempting payment
    # (Calls payment_callback_view)
    path('callback/', views.payment_callback_view, name='payment_callback'),

    # URL that Chapa will send asynchronous webhook notifications to
    # (Calls chapa_webhook_receiver - must be configured in Chapa Dashboard)
    path('webhook/chapa/', views.chapa_webhook_receiver, name='chapa_webhook'),

    # --- Optional: Simple URLs for Success/Failure pages ---
    # You can replace these with more sophisticated views if needed

    # Example URL for a generic success page
    path('success/',
         lambda request: render(request, 'payments/payment_success.html', {'message': 'Your payment was successful!'}),
         name='payment_success_generic'),

    # Example URL for a generic failure page
    path('failure/',
         lambda request: render(request, 'payments/payment_failure.html', {'message': 'Your payment could not be completed.'}),
         name='payment_failure_generic'),

    # You might have specific success/failure views that take the transaction object
    # In that case, the redirects in payment_callback_view would point to those instead.
    # e.g., path('success/<str:tx_ref>/', views.payment_success_detail_view, name='payment_success_detail'),

]