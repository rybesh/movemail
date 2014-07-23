#! /usr/bin/env python

import xml.etree.ElementTree as etree
import email
import imaplib
import smtplib
import os
import re
import sys

from secrets import *

DEBUG = False

if DEBUG:
    imaplib.Debug = 4

ATOM_NS = 'http://www.w3.org/2005/Atom'
APPS_NS = 'http://schemas.google.com/apps/2006'

class Filter:
    listre = re.compile(r'list:\((?P<listid>.+)\)')
    def __init__(self, entry):
        self.id = entry.find('{%s}id' % ATOM_NS).text
        self.msg_ids = []
        self.labels = []
        self.forwardees = []
        self.criteria = []
        self.trash = self.star = self.archive \
            = self.alwaysmarkasimportant = False
        for prop in entry.findall('{%s}property' % APPS_NS):
            name = prop.attrib['name'].lower()
            value = prop.attrib['value']
            if name.startswith('should'):
                self.__dict__[name[6:]] = True
            else:
                handler = getattr(self, 'handle_%s' % name, None)
                if handler is None:
                    self.add_search_criteria(name, value)
                else:
                    handler.__call__(value)
        self.criteria.extend(['NOT', 'FLAGGED'])
        if self.trash:
            self.labels.append('[Gmail]/Trash')
        if self.alwaysmarkasimportant:
            self.labels.append('[Gmail]/Important')
        if self.star:
            self.labels.append('[Gmail]/Starred')
        self.error = None
    def handle_hastheword(self, value):
        match = self.listre.match(value)
        if match:
            self.criteria.extend(
                ['HEADER', '"List-Id"', '"%s"' % match.group('listid')])
    def handle_label(self, value):
        self.labels.append(value)
    def handle_forwardto(self, value):
        self.forwardees.append(value)
    def add_search_criteria(self, name, value):
        self.criteria.append('HEADER')
        self.criteria.append(name.upper())
        self.criteria.append('"%s"' % value)
    def run(self, account, smtp=None):
        try:
            code, response = account.search(None, *self.criteria)
            if code == 'OK':
                self.msg_ids = response[0].split()
                if DEBUG:
                    print '%s\nMatched %s messages.' % (
                        ' '.join(self.criteria), len(self.msg_ids))
                if len(self.msg_ids) > 0:
                    msg_list = ','.join(self.msg_ids)
                    for label in self.labels:
                        code, response = account.copy(msg_list, label)
                        if not code == 'OK':
                            break
                for msg_id in self.msg_ids:
                    forward(account, msg_id, smtp, self.forwardees)
            if not code == 'OK':
                self.error = response[0]
        except imaplib.IMAP4.error as e:
            self.error = e

def fetch_message(account, msg_id):
    code, msg_data = account.fetch(msg_id, '(RFC822)')
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            return email.message_from_string(response_part[1])
    return None

def forward(account, msg_id, smtp, recipients):
    if not smtp: return
    msg = fetch_message(account, msg_id)
    if msg:
        for recipient in recipients:
            sender = 'ryan.b.shaw@gmail.com'
            subject = msg.get('Subject', '')
            if DEBUG:
                print >> sys.stderr, \
                    'Forwarding "%s" to <%s>' % (subject, recipient)
            #msg.replace_header('From', sender)
            msg.replace_header('To', recipient)
            msg.replace_header('Subject', 'Fwd: %s' % subject)
            del msg['CC']
            smtp.sendmail(sender, recipient, msg.as_string())

def movemail(from_account, to_account):
    from_account.select('INBOX')
    to_account.select('INBOX')
    code, msg_ids = from_account.search(None, 'ALL')
    for msg_id in msg_ids[0].split():
        msg = fetch_message(from_account, msg_id)
        if msg:
          if DEBUG:
              for header in [ 'from', 'subject' ]:
                  print >> sys.stderr, '%s: %s' % (header.upper(), msg[header])
          to_account.append('INBOX', '', '', msg.as_string())
          code, response = from_account.store(msg_id, '+FLAGS', r'(\Deleted)')
    
def close(accounts):
    for a in accounts:
        try: a.close()
        except: pass
        a.logout()

def load_filters(filename):
    tree = etree.parse(filename)
    return [ Filter(entry) for entry in tree.findall('{%s}entry' % ATOM_NS) ]

def run_filters(account, filters, smtp=None, expunge=True):
    account.select('INBOX')
    to_delete = set()
    for f in filters:
        f.run(account, smtp)
        msg = None
        if f.error is None:
            if len(f.msg_ids) > 0:
                msg = '%s\nFiltered %s messages.' % (
                    ' '.join(f.criteria), len(f.msg_ids))
                if f.archive:
                    to_delete.update(f.msg_ids)
        else:
            msg = 'Problem running filter %s: %s' % (f.id, f.error)
        if DEBUG and msg is not None:
            print >> sys.stderr, msg
    if expunge and len(to_delete) > 0:
        msg_list = ','.join(to_delete)
        code, response = account.store(msg_list, '+FLAGS', r'(\Deleted)')
        if code == 'OK':
            account.expunge()

frombox = imaplib.IMAP4_SSL(FROM_IMAP)
frombox.login(FROM_USER, FROM_PASSWORD)

tobox = imaplib.IMAP4_SSL(TO_IMAP)
tobox.login(TO_USER, TO_PASSWORD)

tobox_smtp = smtplib.SMTP(TO_SMTP, 587)
tobox_smtp.starttls()
tobox_smtp.login(TO_USER, TO_PASSWORD)
if DEBUG:
    tobox_smtp.set_debuglevel(1)

try:
    filters = load_filters(
        os.path.join(os.path.dirname(__file__), 'mailFilters.xml'))
    run_filters(frombox, filters, smtp=tobox_smtp, expunge=False)
    movemail(frombox, tobox)
    run_filters(tobox, filters)
finally:
    close([frombox, tobox])
    tobox_smtp.quit()
