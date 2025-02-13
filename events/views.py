import json
import logging
logger = logging.getLogger(__name__)

from django.shortcuts import render_to_response
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.template import RequestContext
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView

from .exceptions import NonexistantEvent, PriceMismatch, EventNotInProgress, \
    UnknownOutcome, InsufficientBets, InsufficientCash
from .models import Event, Bet, Transaction
from .utils import create_bets_dict

from bladepolska.http import JSONResponse, JSONResponseBadRequest


class EventsListView(ListView):
    template_name = 'events.html'

    def get_queryset(self):
        return Event.objects.get_events(self.kwargs['mode'])

    def get_context_data(self, *args, **kwargs):
        context = super(EventsListView, self).get_context_data(*args, **kwargs)
        events = list(self.get_queryset())
        context.update({
            'events': events,
            'bets': create_bets_dict(self.request.user, events)
        })
        return context


class EventFacebookObjectDetailView(DetailView):
    template_name = 'facebook_event_detail.html'
    context_object_name = 'event'
    model = Event

    def get_object(self):
        return get_object_or_404(Event, id=self.kwargs['pk'])


class EventDetailView(DetailView):
    template_name = 'event_detail.html'
    context_object_name = 'event'
    model = Event

    def get_event(self):
        return get_object_or_404(Event, id=self.kwargs['pk'])

    def get_context_data(self, *args, **kwargs):
        context = super(EventDetailView, self).get_context_data(*args, **kwargs)
        event = self.get_event()
        bets = create_bets_dict(self.request.user, [event])
        if event.id in bets:
            bet = bets[event.id]
        else:
            bet = None
        user = self.request.user
        if user and user.is_authenticated():
            user_bets = Bet.objects.get_users_bets_for_events(user, [event])
        else:
            user_bets = []
        context.update({
            'event': event,
            'bet': bet,
            'active': 1,
            'event_dict': event.event_dict,
            'bets': user_bets,
            'bet_dicts': [bet.bet_dict for bet in user_bets]
        })
        return context


@login_required
@require_http_methods(["POST"])
@csrf_exempt
@transaction.atomic
def create_transaction(request, event_id):
    data = json.loads(request.body)
    try:
        buy = (data['buy'] == 'True')
        outcome = data['outcome']
        for_price = data['for_price']
    except:
        return HttpResponseBadRequest(_("Something went wrong, try again in a few seconds."))
    try:
        if buy:
            user, event, bet = Bet.objects.buy_a_bet(request.user, event_id, outcome, for_price)
        else:
            user, event, bet = Bet.objects.sell_a_bet(request.user, event_id, outcome, for_price)
    except NonexistantEvent:
        raise Http404
    except PriceMismatch as e:
        result = {
            'error': unicode(e),
            'updates': {
                'events': [
                    e.updated_event.event_dict
                ]
            }
        }
        return JSONResponseBadRequest(json.dumps(result))
    except InsufficientCash as e:
        result = {
            'error': unicode(e),
            'updates': {
                'user': [
                    e.updated_user.statistics_dict
                ]
            }
        }

        return JSONResponseBadRequest(json.dumps(result))
    except InsufficientBets as e:
        result = {
            'error': unicode(e),
            'updates': {
                'bets': [
                    e.updated_bet.bet_dict
                ]
            }
        }

        return JSONResponseBadRequest(json.dumps(result))
    except EventNotInProgress as e:
        result = {
            'error': unicode(e),
        }

        return JSONResponseBadRequest(json.dumps(result))
    except UnknownOutcome as e:
        result = {
            'error': unicode(e),
        }

        return JSONResponseBadRequest(json.dumps(result))

    result = {
        'updates': {
            'bets': [
                bet.bet_dict
            ],
            'events': [
                event.event_dict
            ],
            'user': user.statistics_dict
        }
    }

    return JSONResponse(json.dumps(result))
