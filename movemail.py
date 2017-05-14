#! /usr/bin/env python

import email
import imaplib
import sys
import errno

from socket import error as SocketError

from secrets import (FROM_IMAP, FROM_USER, FROM_PASSWORD,
                     TO_IMAP, TO_USER, TO_PASSWORD)

DEBUG = False

if DEBUG:
    imaplib.Debug = 4


def fetch_message(account, msg_id):
    code, msg_data = account.fetch(msg_id, '(RFC822)')
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            return email.message_from_string(response_part[1])
    return None


def movemail(from_account, to_account):
    from_account.select('INBOX')
    to_account.select('INBOX')
    code, msg_ids = from_account.search(None, 'ALL')
    for msg_id in msg_ids[0].split():
        msg = fetch_message(from_account, msg_id)
        if msg:
            if DEBUG:
                for header in ['from', 'subject']:
                    print >> sys.stderr, \
                        '%s: %s' % (header.upper(), msg[header])
            to_account.append('INBOX', '', '', msg.as_string())
            code, resp = from_account.store(msg_id, '+FLAGS', r'(\Deleted)')


def close(accounts):
    for a in accounts:
        try:
            a.close()
            a.logout()
        except:
            pass


frombox = tobox = None
try:

    frombox = imaplib.IMAP4_SSL(FROM_IMAP)
    frombox.login(FROM_USER, FROM_PASSWORD)

    tobox = imaplib.IMAP4_SSL(TO_IMAP)
    tobox.login(TO_USER, TO_PASSWORD)

    movemail(frombox, tobox)

except SocketError as e:
    # ignore connection resets
    if e.errno != errno.ECONNRESET:
        raise
finally:
    close([frombox, tobox])
