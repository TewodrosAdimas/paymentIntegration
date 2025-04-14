# payments/models.py
from django.db import models
from django.conf import settings
import uuid

class PaymentTransaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    tx_ref = models.CharField(max_length=100, unique=True, default=uuid.uuid4) # Your unique reference
    chapa_transaction_id = models.CharField(max_length=255, blank=True, null=True) # Chapa's ID, store after verification
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='ETB')
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True) # Added based on docs
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment for {self.amount} {self.currency} ({self.tx_ref})"