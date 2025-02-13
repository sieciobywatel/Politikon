# coding: utf-8

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.translation import ugettext as _

from django.template.defaultfilters import slugify
from unidecode import unidecode

from math import exp

from bladepolska.snapshots import SnapshotAddon
from bladepolska.site import current_domain
from .exceptions import NonexistantEvent, PriceMismatch, EventNotInProgress, \
    UnknownOutcome, InsufficientCash, InsufficientBets

from politikon.choices import Choices
from .managers import EventManager, BetManager, TransactionManager

from .managers import EventManager, BetManager, TransactionManager

class Event(models.Model):

    EVENT_OUTCOME_CHOICES = Choices(
        ('IN_PROGRESS', 1, u'w trakcie'),
        ('CANCELLED', 2, u'anulowane'),
        ('FINISHED_YES', 3, u'rozstrzygnięte na TAK'),
        ('FINISHED_NO', 4, u'rozstrzygnięte na NIE'),
    )

    objects = EventManager()
    snapshots = SnapshotAddon(fields=[
        'current_buy_for_price',
        'current_buy_against_price',
        'current_sell_for_price',
        'current_sell_against_price',
        'Q_for',
        'Q_against',
        'B'
    ])

    title = models.TextField(u"tytuł wydarzenia")
    short_title = models.TextField(u"tytuł promocyjny wydarzenia")

    title_fb_yes = models.TextField(u"tytuł na TAK obiektu FB")
    title_fb_no = models.TextField(u"tytuł na NIE obiektu FB")

    description = models.TextField(u"pełny opis wydarzenia", default='')

    small_image = models.ImageField(u"mały obrazek 340x250", upload_to="events_small", null=True)
    big_image = models.ImageField(u"duży obrazek 1250x510", upload_to="events_big", null=True)

    is_featured = models.BooleanField(u"featured", default=False)
    is_front = models.BooleanField(u"front", default=False)
    outcome = models.PositiveIntegerField(u"rozstrzygnięcie", choices=EVENT_OUTCOME_CHOICES, default=1)

    created_date = models.DateTimeField(auto_now_add=True)
    estimated_end_date = models.DateTimeField(u"przewidywana data rozstrzygnięcia")
    end_date = models.DateTimeField(u"data rozstrzygnięcia", null=True)

    current_buy_for_price = models.IntegerField(u"cena nabycia akcji zdarzenia", default=50.0)
    current_buy_against_price = models.IntegerField(u"cena nabycia akcji zdarzenia przeciwnego", default=50.0)
    current_sell_for_price = models.IntegerField(u"cena sprzedaży akcji zdarzenia", default=50.0)
    current_sell_against_price = models.IntegerField(u"cena sprzedaży akcji zdarzenia przeciwnego", default=50.0)

    last_transaction_date = models.DateTimeField(u"data ostatniej transakcji", null=True)

    Q_for = models.IntegerField(u"zakładów na TAK", default=0)
    Q_against = models.IntegerField(u"zakładów na NIE", default=0)
    turnover = models.IntegerField(u"obrót", default=0, db_index=True)

    absolute_price_change = models.IntegerField(u"zmiana ceny (wartość absolutna)", db_index=True, default=0)
    price_change = models.IntegerField(u"zmiana ceny", default=0)

    B = models.FloatField(u"stała B", default=5)

    def __unicode__(self):
        return self.title

    def get_relative_url(self):
        return "/event/%(id)d-%(title)s" % { 'id' : self.id, 'title': slugify(unidecode(self.title))}

    def get_absolute_url(self):
        return "http://%(domain)s%(url)s" % {
            'domain': current_domain(),
            'url': reverse("events:event_detail", kwargs={'event_id': self.id})
        }

    def get_absolute_facebook_object_url(self):
        return "http://%(domain)s%(url)s" % {
            'domain': current_domain(),
            'url': reverse("events:event_facebook_object_detail", kwargs={'event_id': self.id})
        }

    @property
    def is_in_progress(self):
        return self.outcome == EVENT_OUTCOME_CHOICES.IN_PROGRESS

    @property
    def publish_channel(self):
        return "event_%d" % self.id

    @property
    def event_dict(self):
        return {
            'event_id': self.id,
            'buy_for_price': self.current_buy_for_price,
            'buy_against_price': self.current_buy_against_price,
            'sell_for_price': self.current_sell_for_price,
            'sell_against_price': self.current_sell_against_price,
        }

    def price_for_outcome(self, outcome, direction='BUY'):
        if (direction, outcome) not in BET_OUTCOMES_TO_PRICE_ATTR:
            raise UnknownOutcome()

        attr = BET_OUTCOMES_TO_PRICE_ATTR[(direction, outcome)]
        return getattr(self, attr)

    def increment_quantity(self, outcome, by_amount):
        if outcome not in BET_OUTCOMES_TO_QUANTITY_ATTR:
            raise UnknownOutcome()

        attr = BET_OUTCOMES_TO_QUANTITY_ATTR[outcome]
        setattr(self, attr, getattr(self, attr) + by_amount)

        self.recalculate_prices()

    def increment_turnover(self, by_amount):
        self.turnover += by_amount;

    def recalculate_prices(self):
        factor = 100.

        B = self.B

        Q_for = self.Q_for
        Q_against = self.Q_against
        Q_for_sell = max(0, Q_for - 1)
        Q_against_sell = max(0, Q_against - 1)

        e_for_buy = exp(Q_for / B)
        e_against_buy = exp(Q_against / B)
        e_for_sell = exp(Q_for_sell / B)
        e_against_sell = exp(Q_against_sell / B)

        buy_for_price = e_for_buy / float(e_for_buy + e_against_buy)
        buy_against_price = e_against_buy / float(e_for_buy + e_against_buy)
        sell_for_price = e_for_sell / float(e_for_sell + e_against_buy)
        sell_against_price = e_against_sell / float(e_for_buy + e_against_sell)

        self.current_buy_for_price = round(factor * buy_for_price,0)
        self.current_buy_against_price = round(factor * buy_against_price,0)
        self.current_sell_for_price = round(factor * sell_for_price,0)
        self.current_sell_against_price = round(factor * sell_against_price,0)

    def save(self, **kwargs):
        if not self.id:
            self.recalculate_prices()

        super(Event, self).save(**kwargs)


class Bet(models.Model):

    BET_OUTCOME_CHOICES = Choices(
        ('YES', True, u'udziały na TAK'),
        ('NO', False, u'udziały na NIE'),
    )

    BET_OUTCOMES_TO_PRICE_ATTR = {
        ('BUY', 'YES'): 'current_buy_for_price',
        ('BUY', 'NO'): 'current_buy_against_price',
        ('SELL', 'YES'): 'current_sell_for_price',
        ('SELL', 'NO'): 'current_sell_against_price'
    }

    BET_OUTCOMES_TO_QUANTITY_ATTR = {
        'YES': 'Q_for',
        'NO': 'Q_against'
    }


    objects = BetManager()

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=False, related_name='bets', related_query_name='bet')
    event = models.ForeignKey(Event, null=False, related_name='bets', related_query_name='bet')
    outcome = models.BooleanField(u'zakład na TAK', choices=BET_OUTCOME_CHOICES)
    has = models.PositiveIntegerField(u"posiadane zakłady", default=0, null=False)
    bought = models.PositiveIntegerField(u"kupione zakłady", default=0, null=False)
    sold = models.PositiveIntegerField(u"sprzedane zakłady", default=0, null=False)
    bought_avg_price = models.FloatField(u"kupione po średniej cenie", default=0, null=False)
    sold_avg_price = models.FloatField(u"sprzedane po średniej cenie", default=0, null=False)
    rewarded_total = models.IntegerField(u"nagroda za wynik", default=0, null=False)

    @property
    def bet_dict(self):
        return {
            'bet_id': self.id,
            'event_id': self.event.id,
            'user_id': self.user.id,
            'outcome': self.outcome,
            'has': self.has,
            'bought': self.bought,
            'sold': self.sold,
            'bought_avg_price': self.bought_avg_price,
            'sold_avg_price': self.sold_avg_price,
            'rewarded_total': self.rewarded_total,
        }

    def __unicode__(self):
        return u"zakłady %s na %s" % (self.user, self.event)


class Transaction(models.Model):

    TRANSACTION_TYPE_CHOICES = Choices(
        ('BUY_YES', 1, u'zakup udziałów na TAK'),
        ('SELL_YES', 2, u'sprzedaż udziałów na TAK'),
        ('BUY_NO', 3, u'zakup udziałów na NIE'),
        ('SELL_NO', 4, u'sprzedaż udziałów na NIE'),
        ('EVENT_CANCELLED_REFUND', 5, u'zwrot po anulowaniu wydarzenia'),
        ('EVENT_WON_PRIZE', 6, u'wygrana po rozstrzygnięciu wydarzenia'),
        ('TOPPED_UP_BY_APP', 7, u'doładowanie konta przez aplikację'),
    )

    objects = TransactionManager()

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=False, related_name='transactions', related_query_name='transaction')
    event = models.ForeignKey(Event, null=True, related_name='transactions', related_query_name='transaction')
    type = models.PositiveIntegerField("rodzaj transakcji", choices=TRANSACTION_TYPE_CHOICES, default=1)
    date = models.DateTimeField(auto_now_add=True)
    quantity = models.PositiveIntegerField(u"ilość", default=1)
    price = models.IntegerField(u"cena jednostkowa", default=0, null=False)

    def __unicode__(self):
        return "%s przez %s" % (self.TRANSACTION_TYPE_CHOICES[self.type].label, self.user)
