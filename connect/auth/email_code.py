# Copyright (c) 2026
# For license information, please see license.txt

"""A one-time code that proves the holder reads one mailbox.

A 6-digit code that lasts 10 minutes. 5 wrong tries lock it, a resend keeps the count so it
can't be used to keep guessing, and a lock makes sure one code signs in once. Only a hash of
the code is kept in the cache, never the code itself.
"""

import hashlib
import hmac
import secrets
from contextlib import contextmanager

import frappe
from frappe import _


class EmailCodeError(frappe.ValidationError):
	"""The code is wrong, expired or locked."""


class EmailCode:
	TTL_SECONDS = 10 * 60
	MAX_ATTEMPTS = 5

	def __init__(self, email):
		self.email = email
		self.cache_key = f"connect:email-code:{email}"

	@property
	def pending(self):
		"""What's kept for this email: the code's hash, the wrong tries, and the sign-up details
		given when the code was asked for. None once it has expired or been used."""
		return frappe.cache.get_value(self.cache_key, use_local_cache=False)

	def send(self, subject, heading, details=None):
		"""Email a fresh code. Wrong tries carry over, so a resend can't reset the lock; the
		sign-up details are kept from the first request unless new ones are given."""
		pending = self.pending or {}
		attempts = pending.get("attempts", 0)
		if attempts >= self.MAX_ATTEMPTS:
			self._throw_locked()

		code = f"{secrets.randbelow(900_000) + 100_000}"
		self._store(
			{
				"code_hash": self._hash(code),
				"attempts": attempts,
				"details": {**(pending.get("details") or {}), **{k: v for k, v in (details or {}).items() if v}},
			}
		)
		if frappe.conf.developer_mode:
			# A local bench usually can't send email, so the code is in logs/connect.auth.log too (as a warning: the dev server logs nothing quieter).
			frappe.logger("connect.auth").warning(f"Sign-in code for {self.email}: {code}")
		self._mail(code, subject.format(code), heading)

	@contextmanager
	def lock(self):
		"""Hold while a code is checked and spent, so one code signs in once."""
		with frappe.cache.lock(frappe.cache.make_key(f"{self.cache_key}:lock"), timeout=10):
			yield

	def verify(self, code):
		"""The pending entry for a correct code. A wrong code counts as a try."""
		pending = self.pending
		if not pending:
			frappe.throw(_("That code has expired. Request a new code."), EmailCodeError)
		if pending["attempts"] >= self.MAX_ATTEMPTS:
			self._throw_locked()

		if not hmac.compare_digest(pending["code_hash"], self._hash(code)):
			pending["attempts"] += 1
			self._store(pending)
			left = self.MAX_ATTEMPTS - pending["attempts"]
			if not left:
				self._throw_locked()
			frappe.throw(
				_("That code is incorrect. Check your latest email and try again ({0} left).").format(left),
				EmailCodeError,
			)
		return pending

	def remember(self, details):
		"""Keep details given after the code was checked (Set up your profile), for the same code."""
		pending = self.pending
		if pending:
			pending["details"] = {**(pending.get("details") or {}), **{k: v for k, v in details.items() if v}}
			self._store(pending)

	def discard(self):
		frappe.cache.delete_value(self.cache_key)

	def _hash(self, code):
		# Keyed with the site's secret, so a leaked cache entry can't be checked against all
		# 900,000 codes offline.
		key = (frappe.local.conf.get("secret_key") or frappe.local.site).encode()
		return hmac.new(key, f"{self.email}:{code}".encode(), hashlib.sha256).hexdigest()

	def _store(self, pending):
		frappe.cache.set_value(self.cache_key, pending, expires_in_sec=self.TTL_SECONDS)

	def _mail(self, code, subject, heading):
		try:
			frappe.sendmail(
				recipients=[self.email],
				subject=subject,
				template="connect_sign_in_code",
				args={"code": code, "heading": heading, "expires_minutes": self.TTL_SECONDS // 60},
				now=True,
			)
		except Exception:
			frappe.log_error(title="Sign-in code could not be sent")
			# A mail error can queue its own message; the person should only read ours.
			frappe.clear_messages()
			if frappe.conf.developer_mode:
				return  # the code is in the log
			frappe.throw(_("We could not send a code to this email. Check the address and try again."))

	def _throw_locked(self):
		frappe.throw(
			_("Too many incorrect codes. Wait {0} minutes, then request a new code.").format(
				self.TTL_SECONDS // 60
			),
			EmailCodeError,
		)
