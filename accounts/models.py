# coding: utf-8
import datetime
import logging
import urllib2

from django.contrib.auth.models import AbstractBaseUser, User
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import F, Q
from django.core.urlresolvers import reverse
from politikon.settings import STATIC_URL

from bladepolska.snapshots import SnapshotAddon
from constance import config

from .managers import UserProfileManager
from .utils import format_int, save_profile

from events.models import Bet, Event


logger = logging.getLogger(__name__)


class UserProfile(AbstractBaseUser):

    objects = UserProfileManager()
    # przeliczane rankingi: ranking, miesiąc, tydzień
    snapshots = SnapshotAddon(fields=[
        'total_cash',
        'total_given_cash',
        'portfolio_value'
    ])

    username = models.CharField(u"username", max_length=100, unique=True)
    email = models.CharField(u"email", max_length=255)
    avatarURL = models.CharField(u"avatar_url", max_length=255, default='')

    name = models.CharField(max_length=100, blank=True)
    is_admin = models.BooleanField(u"is an administrator", default=False)
    is_deleted = models.BooleanField(u"is deleted", default=False)

    is_staff = models.BooleanField(u"is staff", default=False)
    is_active = models.BooleanField(u"is active", default=False)

    is_vip = models.BooleanField(u"VIP", default=False)

    created_date = models.DateTimeField(auto_now_add=True)

    # Every new network relations also has to have 'related_name="django_user"'
    #     facebook_user = models.OneToOneField(FacebookUser, null=True, related_name="django_user", on_delete=models.SET_NULL)

    friends = models.ManyToManyField('self', related_name='friend_of')

    total_cash = models.IntegerField(u"ilość gotówki", default=0.)

    total_given_cash = models.IntegerField(u"ilość przyznanej gotówki w historii", default=0.)
    reputation = models.DecimalField(u"reputation", default=0, max_digits=12, decimal_places=2,)
    unused_reput = models.IntegerField(u"wolne reputy", default=0)

    portfolio_value = models.IntegerField(u"wartość portfela", default=0.)

    description = models.CharField(u"krótki opis", max_length=255, default='')
    facebook_user_id = models.IntegerField(u"facebook ID", default=None, blank=True, null=True)
    facebook_user = models.CharField(u"facebook URL", max_length=255, default=None, blank=True, null=True)
    twitter_user_id = models.IntegerField(u"twitter ID", default=None, blank=True, null=True)
    twitter_user = models.CharField(u"twitter URL", max_length=255, default=None, blank=True, null=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def __unicode__(self):
        return "%s" % self.username

    @transaction.atomic
    def synchronize_facebook_friends(self):
        # Get friends
        facebook_friends_ids = self.facebook_user.friends_using_our_app
        if facebook_friends_ids is None:
            return

        # django_friends_ids = FacebookUser.objects.django_users_for_ids(facebook_friends_ids).values_list('id', flat=True)
        # django_friends_ids_set = set(django_friends_ids)

        friends_through_model = self.friends.through
        friends_manager = friends_through_model.objects

        # Get current relations
        current_friends_ids_set = self.friends_ids_set

        # Add new
        new_friends_ids = list(django_friends_ids_set - current_friends_ids_set)
        logger.debug("'User::synchronize_facebook_friends' adding %d new friends." % len(new_friends_ids))

        if new_friends_ids:
            new_friends_through = [friends_through_model(from_user=self, to_user_id=friend_id) for friend_id in
                                   new_friends_ids]
            friends_manager.bulk_create(new_friends_through)

        # Remove stale
        stale_friends_ids = list(current_friends_ids_set - django_friends_ids_set)
        logger.debug("'User::synchronize_facebook_friends' removing %d stale friends." % len(stale_friends_ids))

        if stale_friends_ids:
            first_way_qs = Q(from_user=self, to_user__in=stale_friends_ids)
            second_way_qs = Q(to_user=self, from_user__in=stale_friends_ids)
            friends_manager.filter(first_way_qs | second_way_qs).delete()

    @property
    def statistics_dict(self):
        return {
            'user_id': self.id,
            'total_cash': self.total_cash_formatted,
            'portfolio_value': self.portfolio_value_formatted,
            'reputation': self.reputation
        }

    @property
    def friends_ids_set(self):
        friends_through_model = self.friends.through
        friends_manager = friends_through_model.objects

        current_friends_ids = friends_manager.filter(Q(from_user=self) | Q(to_user=self)).values_list('from_user_id',
                                                                                                      'to_user_id')

        current_friends_ids_set = set()
        for from_id, to_id in current_friends_ids:
            if from_id != self.id:
                current_friends_ids_set.add(from_id)
            if to_id != self.id:
                current_friends_ids_set.add(to_id)

        return current_friends_ids_set


    def get_full_name(self):
        return "%s (%s)" % (self.name, self.username)

    @property
    def full_name(self):
        return self.get_full_name()

    def get_short_name(self):
        return self.name

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True

    @property
    def current_portfolio_value(self):
        portfolio_value = 0
        user_bets = Bet.objects \
            .select_related('event') \
            .filter(user=self,
                    event__outcome=Event.EVENT_OUTCOME_CHOICES.IN_PROGRESS_CHOICE.value)

        for bet in user_bets.iterator():
            price_field = "current_sell_for_price"
            if bet.outcome is False:
                price_field = "current_sell_against_price"

            portfolio_value += bet.has * getattr(bet.event, price_field)

        return portfolio_value

    @property
    def portfolio_value_formatted(self):
        return format_int(self.portfolio_value)

    @property
    def total_cash_formatted(self):
        return format_int(self.total_cash)

    def calc_reputation(self):
        if float(self.total_given_cash) == 0:
            self.reputation = 0
        else:
            self.reputation = round(self.portfolio_value / float(self.total_given_cash), 2)

    @property
    def profile_photo(self):
        if self.facebook_user:
            return self.facebook_user.profile_photo

    def topup_cash(self, amount):
        self.total_cash = F('total_cash') + amount
        self.total_given_cash = F('total_given_cash') + amount

        from events.models import Transaction, TRANSACTION_TYPES_DICT

        transaction = Transaction.objects.create(
            user=self, type=TRANSACTION_TYPES_DICT['TOPPED_UP_BY_APP'],
            quantity=1, price=amount)

        # from canvas.models import ActivityLog
        # ActivityLog.objects.register_transaction_activity(self, transaction)

        self.save(update_fields=['total_cash', 'total_given_cash'])

    @property
    def is_superuser(self):
        return self.is_admin

    def get_absolute_url(self):
        """
        Get this user url

        :return: user url
        :rtype: str
        """
        return reverse('accounts:user', kwargs={'pk': str(self.pk)})

    def get_avatar_url(self):
        """
        Get this user avatar url

        :return: avatar url
        :rtype: str
        """
        if self.avatarURL:
            return self.avatarURL
        else:
            return STATIC_URL + "img/blank-avatar.jpg"
