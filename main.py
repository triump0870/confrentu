#!/usr/bin/env python
import webapp2

from google.appengine.api import app_identity
from google.appengine.api import mail

from conference import ConferenceApi

class SetAnnouncementHandler(webapp2.RequestHandler):
	def get(self):
		"""Set announcement in memcache"""
		ConferenceApi._cacheAnnouncements()

class SendConfirmationEmailHandler(webapp2.RequestHandler):
	def post(self):
		"""Send email confirming Conference creation."""
		mail.send_mail(
			'noreply@%s.appspotmail.com'%(
				app_identity.get_application_id()),
			self.request.get('email'),
			'You have created a new Conference!',
			'Hi, you have created following '
			'conference:\r\n\r\n%s' % self.request.get('conferenceInfo')
		)
app = webapp2.WSGIApplication([
	('/crons/set_announcement', SetAnnouncementHandler),
	('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
	], debug=True)