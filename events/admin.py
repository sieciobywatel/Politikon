from django.contrib import admin

from models import *


class EventAdmin(admin.ModelAdmin):
    readonly_fields = [
        'outcome',
        'current_buy_for_price',
        'current_buy_against_price',
        'current_sell_for_price',
        'current_sell_against_price',
        'last_transaction_date',
        'Q_for',
        'Q_against',
    ]

    list_display = ['id', 'title', 'is_featured', 'outcome', 'created_date', 'estimated_end_date', 'current_buy_for_price', 'current_buy_against_price', 'Q_for', 'Q_against',
]


class BetAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'event', 'outcome', 'has', 'bought', 'sold', 'bought_avg_price', 'sold_avg_price', 'rewarded_total']


class TransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'event', 'type', 'date', 'quantity', 'price']


admin.site.register(Event, EventAdmin)
admin.site.register(Bet, BetAdmin)
admin.site.register(Transaction, TransactionAdmin)
