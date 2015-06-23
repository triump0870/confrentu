#!/usr/bin/env python

__author__ = 'b4you0870@google.com (Rohan Roy)'


from datetime import datetime
import json
import os
import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import urlfetch
from google.appengine.ext import ndb

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize

from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms

from models import BooleanMessage
from models import ConflictException

from settings import WEB_CLIENT_ID

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey = messages.StringField(1),
)


CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey = messages.StringField(1),
)

# - - - Global Values - - - - - - - - - - - - - - - - - - - 

DEFAULTS = {
    "city": "Kolkata",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "New Conference", "Programming" ],
    }

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
    }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
    }

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)

        profile = p_key.get()
        if not profile:
            profile = Profile(
                userId = user_id,
                key = p_key,
                displayName = user.nickname(), 
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
                
            )

            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            prof.put()
            
        # return ProfileForm
        return self._copyProfileToForm(prof)

    # - - - Endpoints Methods - - - - - - - - - - - - - - - - - - - - - - - 
    
    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Conference objects - - - - - - - - - - - - - - - - -
    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filter in filters:
            if filter['field'] in ['month', 'maxAttendees']:
                filter['value'] = int(filter['value'])
            elif filter['field'] in ['city', 'topics']:
                filter['value'] = filter['value'].title()
            formatted_query = ndb.query.FilterNode(filter['field'], filter['operator'], filter['value'])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filter = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filter['field'] = FIELDS[filter['field']]
                filter['operator'] = OPERATORS[filter['operator']]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is inequality
            if filter['operator'] != "=":
                if inequality_field and inequality_field != filter['field']:
                    raise endpoints.BadRequestException('Inequality filter is allowed on only one field.')
                else:
                    inequality_field = filter['field']


            formatted_filters.append(filter)
        return (inequality_field, formatted_filters)



    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())

        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        Conference(**data).put()

        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        """Return updated ConferenceForm"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy conferenceform/protoRPC message into dict
        data = {field.name:getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endswith.NotFoundException('No conference found with key:%s'%request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                    'Only the owner can update the conference')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if field.name not in (None,[]):
                # special handling for dates (convert string to date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime("%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month

                # write to conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)
        
        organizers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        
        profiles = ndb.get_multi(organizers)

        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName
         # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) \
            for conf in conferences]
        )

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
        path='conference/{websafeConferenceKey}',
        http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference -- provided field & return updated ConferenceForm."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
        path='conference/{websafeConferenceKey}',
        http_method="GET", name='getConference')
    def getConference(self, request):
        """Return requested conference by websafeConferenceKey."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException('No conference found with key=%s'%request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='getConferencesCreated',
        http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, displayName) for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, ConferenceForms,
        path='conference/attending',
        http_method='GET', name='getConferencesToAttend')
    def getConferencesAttend(self, request):
        """Get list of conferences that user has registered for."""

        # Get user profile from the user
        user = self._getProfileFromUser()

        # get all the conference keys that user will attend or attended
        confToAttend = [ndb.Key(urlsafe=key) for key in user.conferenceKeysToAttend]

        # Fetch all the conferences from the datastore maching the keys at once
        conferences = ndb.get_multi(confToAttend)

        # Extract the organizerUserId from the conferences
        names = [conf.organizerUserId for conf in conferences]

        # get the profiles of the organizers
        p_keys = [ndb.Key(Profile, name) for name in names]
        profiles = ndb.get_multi(p_keys)

        display = {}
        for profile in profiles:
            display[profile.key.id()] = profile.displayName

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, display[conf.organizerUserId]) for conf in conferences]
        )

# - - - Registration - - - - - - - - - - - - - - - - - - - - - - - - 
    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = True
        prof = self._getProfileFromUser() # get user profile 

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endswith.NotFoundException(
                'No conference found with key: %s'%wsck)

        # register
        if reg:
            # check if user already register otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    'You have already registered for this conference')

            # check if seats available
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat 
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False


        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
        path='conference/{websafeConferenceKey}',
        http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
        path='Conference/{websafeConferenceKey}',
        http_method='GET', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user from selected conference."""
        return self._conferenceRegistration(request, reg=False)


# registers API
api = endpoints.api_server([ConferenceApi]) 