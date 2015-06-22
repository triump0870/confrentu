"""It creates a unique userid which will be saved in the
google datastore."""

import json
import os
import time
import uuid

from google.appengine.api import urlfetch
from models import Profile

def getUserId(user, id_type="email"):
	if id_type == "email":
		return user.email()

	if id_type == "oauth":
		""" A workaround implementation for getting useid."""
		auth = os.getenv('HTTP_AUTHORIZATION')
		bearer , token = auth.split()
		token_type = 'id_token'
		if 'OAUTH_USER_ID' in os.environ:
			token_type = 'access_token'
		url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'%(token_type, token))
		user = {}
		wait = 1
		for i in xrange(3):
			resp = urlfetch.fetch(url)
			if resp.status_code == 200:
				user = json.loads(resp.content)
				break
			elif resp.status_code == 400 and 'invalid_token' in resp.content:
				url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'%('access_token', token))
			else:
				time.sleep(wait)
				wait += i
		return user.get('user_id', '')

	if id_type == 'custom':
		profile = Conference.query(Conference.mainEmail == user.email())
		return profile.id()
	else:
		return str(uuid.uuid1().get_hex())