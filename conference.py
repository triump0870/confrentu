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

from settings import WEB_CLIENT_ID

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

# - - - Default Values - - - - - - - - - - - - - - - - - - - 

DEFAULTS = {
    "city": "Kolkata",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "New Conference", "Programming" ],
    }

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api( name='conference',
                version='v2',
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
                displayName = "Fucker", 
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

# - - - Conference Objects - - - - - - - - - - - - - - - - - - - - - - 

    def _copyConferenceForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        conferenceForm = ConferenceForm()
        for field in conferenceForm.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(conferenceForm, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(conferenceForm, field.name, getattr(conf, field.name))
            elif field.name == 'websafekey':
                setattr(conferenceForm, field.name, conf.key.urlsafe())
        if displayName:
            setattr(conferenceForm, 'organizerDisplayName', displayName)
        conferenceForm.check_initialized()
        return conferenceForm

    def _creteConfereneceObject(self, request):
        """Crete or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/protoRPC Message into dict.
        data = {field.name:getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for default in DEFAULTS:
            if data[default] in (None, []):
                data[default] = DEFAULTS[default]
                setattr(request, default, DEFAULTS[default])

        # convert dates from stringd to DAte objects; set month based on startDate
        if data['startDate']:
            # date, time = data['startDate'].split()
            data[startDate] = datetime.strptime(data['startDate'], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            # date, time = data['endDate'].split()
            date['endDate'] = datetime.strptime(data['endDate'][:10],"%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message.
        if data['maxAttendees'] > 0:
            data['seatsAvailable'] = data['maxAttendees']
            setattr(request, 'seatsAvailable', data['maxAttendees'])

        # Make Profile key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID using Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        return request



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

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference', http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new Conference"""
        return self._creteConfereneceObject(request)


# registers API
api = endpoints.api_server([ConferenceApi]) 
