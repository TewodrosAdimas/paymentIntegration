# payment_project/urls.py

from django.contrib import admin
from django.urls import path, include # Make sure include is imported
from django.shortcuts import render # For a simple homepage maybe

urlpatterns = [
    path('admin/', admin.site.urls),

    # Include the URLs from the 'payments' app under the 'payments/' prefix
    # Make sure to use the correct namespace ('payments') matching app_name in payments/urls.py
    path('', include('payments.urls', namespace='payments')),

    # Add other app URLs here
    # path('orders/', include('orders.urls', namespace='orders')),
    # path('accounts/', include('django.contrib.auth.urls')), # Example for auth

    # Optional: Add a simple homepage view for testing
    path('', lambda request: render(request, 'home.html'), name='home'), # Create home.html template

]