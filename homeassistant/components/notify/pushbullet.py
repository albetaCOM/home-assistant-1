"""
Pushbullet platform for notify component.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/notify.pushbullet/
"""
import logging

import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_DATA, ATTR_TARGET, ATTR_TITLE, ATTR_TITLE_DEFAULT,
    PLATFORM_SCHEMA, BaseNotificationService)
from homeassistant.const import CONF_API_KEY
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['pushbullet.py==0.11.0']

_LOGGER = logging.getLogger(__name__)

ATTR_URL = 'url'
ATTR_FILE = 'file'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_KEY): cv.string,
})


# pylint: disable=unused-argument
def get_service(hass, config, discovery_info=None):
    """Get the Pushbullet notification service."""
    from pushbullet import PushBullet
    from pushbullet import InvalidKeyError

    try:
        pushbullet = PushBullet(config[CONF_API_KEY])
    except InvalidKeyError:
        _LOGGER.error("Wrong API key supplied")
        return None

    return PushBulletNotificationService(pushbullet)


class PushBulletNotificationService(BaseNotificationService):
    """Implement the notification service for Pushbullet."""

    def __init__(self, pb):
        """Initialize the service."""
        self.pushbullet = pb
        self.pbtargets = {}
        self.refresh()

    def refresh(self):
        """Refresh devices, contacts, etc.

        pbtargets stores all targets available from this Pushbullet instance
        into a dict. These are Pushbullet objects!. It sacrifices a bit of
        memory for faster processing at send_message.

        As of sept 2015, contacts were replaced by chats. This is not
        implemented in the module yet.
        """
        self.pushbullet.refresh()
        self.pbtargets = {
            'device': {
                tgt.nickname.lower(): tgt for tgt in self.pushbullet.devices},
            'channel': {
                tgt.channel_tag.lower(): tgt for
                tgt in self.pushbullet.channels},
        }

    def send_message(self, message=None, **kwargs):
        """Send a message to a specified target.

        If no target specified, a 'normal' push will be sent to all devices
        linked to the Pushbullet account.
        Email is special, these are assumed to always exist. We use a special
        call which doesn't require a push object.
        """
        targets = kwargs.get(ATTR_TARGET)
        title = kwargs.get(ATTR_TITLE, ATTR_TITLE_DEFAULT)
        data = kwargs.get(ATTR_DATA)
        url = None
        filepath = None
        if data:
            url = data.get(ATTR_URL, None)
            filepath = data.get(ATTR_FILE, None)
        refreshed = False

        if not targets:
            # Backward compatibility, notify all devices in own account
            self._push_data(filepath, message, title, url, self.pushbullet)
            _LOGGER.info("Sent notification to self")
            return

        # Main loop, process all targets specified
        for target in targets:
            try:
                ttype, tname = target.split('/', 1)
            except ValueError:
                _LOGGER.error("Invalid target syntax: %s", target)
                continue

            # Target is email, send directly, don't use a target object
            # This also seems works to send to all devices in own account
            if ttype == 'email':
                self._push_data(filepath, message, title, url,
                                self.pushbullet, tname)
                _LOGGER.info("Sent notification to email %s", tname)
                continue

            # Refresh if name not found. While awaiting periodic refresh
            # solution in component, poor mans refresh ;)
            if ttype not in self.pbtargets:
                _LOGGER.error("Invalid target syntax: %s", target)
                continue

            tname = tname.lower()

            if tname not in self.pbtargets[ttype] and not refreshed:
                self.refresh()
                refreshed = True

            # Attempt push_note on a dict value. Keys are types & target
            # name. Dict pbtargets has all *actual* targets.
            try:
                self._push_data(filepath, message, title, url,
                                self.pbtargets[ttype][tname])
                _LOGGER.info("Sent notification to %s/%s", ttype, tname)
            except KeyError:
                _LOGGER.error("No such target: %s/%s", ttype, tname)
                continue

    def _push_data(self, filepath, message, title, url, pusher, tname=None):
        from pushbullet import PushError
        from pushbullet import Device
        try:
            if url:
                if isinstance(pusher, Device):
                    pusher.push_link(title, url, body=message)
                else:
                    pusher.push_link(title, url, body=message, email=tname)
            elif filepath and self.hass.config.is_allowed_path(filepath):
                with open(filepath, "rb") as fileh:
                    filedata = self.pushbullet.upload_file(fileh, filepath)
                    if filedata.get('file_type') == 'application/x-empty':
                        _LOGGER.error("Failed to send an empty file.")
                        return
                    pusher.push_file(title=title, body=message, **filedata)
            else:
                if isinstance(pusher, Device):
                    pusher.push_note(title, message)
                else:
                    pusher.push_note(title, message, email=tname)
        except PushError as err:
            _LOGGER.error("Notify failed: %s", err)
