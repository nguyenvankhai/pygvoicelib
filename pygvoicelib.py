import urllib
import urllib2
import re
try:
    import json
except ImportError:
    import simplejson as json


__author__ = 'Ehsan Foroughi'
__email__ = 'ehsan.foroughi@teltub.com',
__copyright__ = 'Copyright 2010, TELTUB Inc'
__credits__ = ['Ehsan Foroughi']
__license__ = 'GPLv3'
__version__ = '1.0'
__all__ = ['GoogleVoice', 'GoVoError', 'LoginError', 'ServerError']

DEFAULT_CAPTCHA_RETRY = 5

GET_JSON_RE = re.compile(r'<json><!\[CDATA(.+)\]></json>\n', re.MULTILINE)
RNR_SE_RE = re.compile(r"'_rnr_se': '(.+)'")

CONTENT_TYPE = 'application/x-www-form-urlencoded;charset=utf-8'
USER_AGENT = 'Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US; rv:1.9.1.13) Gecko/20100914 Firefox/3.5.13 (.NET CLR 3.5.30729)'
REQ_HEADER = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8', 'User-Agent': USER_AGENT}

SERVICE = 'grandcentral'
ACC_TYPE = 'GOOGLE_OR_HOSTED'
APP_SOURCE = 'TELTUB-PlatForm-1.0'
AUTH_ARGS = {'accountType':ACC_TYPE, 'source':APP_SOURCE, 'service':SERVICE}
AUTH_URL = 'https://www.google.com/accounts/ClientLogin'
CAPTCHA_URL_PREFIX = 'http://www.google.com/accounts/'
BASE_URL = 'https://www.google.com/voice'
INDEX_URL = '/'
SETTINGS_URL = '/settings/tab/phones'
CALL_URL = '/call/connect/'
CANCEL_URL = '/call/cancel/'
DEL_FORWARD_URL = '/settings/deleteForwarding/'
EDIT_FORWARD_URL = '/settings/editDefaultForwarding/'
PORTING_URL = '/service/post'

LOGIN_ERR_MSG = 'You have not yet setup your Google Voice account. Please <a href="http://googe.com/voice" target="_blank" style="text-decoration:underline">configure your Google Voice</a> and try again.'

class GoVoError(Exception):
    pass

class LoginError(GoVoError):
    """
    The Exception class to handle Login/Authentication errors
    See <reason> for more details.
    Legend for <reason>:
        'failed': Credentials are invalid.
        'captcha': Account is locked awaiting a captcha unlock.
        'error': An unknown/unexpected error has occured.
    Note that 'failed' and 'captcha' are expected in normal operation flow.
    """
    def __init__(self, reason, msg):
        Exception.__init__(self, reason, msg)
        self.reason = reason
        self.msg = msg

class ServerError(GoVoError):
    """
    The Exception class to handle ServerErrors.
    Note that these errors are not expected in normal operation flow
    """
    def __init__(self, code, msg):
        Exception.__init__(self, code, msg)
        self.code = code
        self.msg = msg

class GoogleVoice:
    def __init__(self, user, passwd, auth_token=None, rnr_se=None):
        """
        Initialize either using just <user> and <passwd>,
        or pass all parameters from a saved state (see get_state).

        Parameters:
            <user>: can be username@gmail.com or username
            <passwd>: password
            <auth_token>: [optional] is the token for Google's ClientLogin interface.
            <rnr_se>: [optional] is the internal variable used by Google Voice.
        """
        self.user = user
        self.passwd = passwd
        self.auth_token = auth_token
        self.rnr_se = rnr_se
        self.reset_captcha()
        self.handle_captcha_entry = None
        self.handle_save_token = None
        self.account_settings = None

    def _get_url_data(self, url, data, header=None):
        req_header = REQ_HEADER
        if header:
            req_header = req_header.copy()
            req_header.update(header)
        data = urllib.urlencode(data)
        if data == '':
            data = None
        request = urllib2.Request(url, data, req_header)
        err_code = None
        try:
            resp_obj = urllib2.urlopen(request)
        except urllib2.HTTPError, e:
            err_code = e.code
            return err_code, e.read()
        resp = resp_obj.read()
        resp_obj.close()
        return None, resp

    def _get_rnr_se(self):
        ret = self.get_auth_url(INDEX_URL, mode='raw', with_retry=False)
        rnr_se = RNR_SE_RE.search(ret)
        if rnr_se:
            rnr_se = rnr_se.groups()[0]
        else:
            if 'not available in your country' in ret:
                raise LoginError('countryerror', LOGIN_ERR_MSG)
            else:
                raise LoginError('error', 'Unable to get rnr_se token')
        self.rnr_se = rnr_se

    def _process_resp(self, resp):
        ret_data = {}
        for line in resp.split('\n'):
            if '=' in line:
                var, val = line.split('=', 1)
                ret_data[var] = val
        return ret_data

    def _get_auth_token(self, captcha_retry=DEFAULT_CAPTCHA_RETRY):
        data = AUTH_ARGS.copy()
        data.update({'Email':self.user, 'Passwd':self.passwd})
        if self.captcha_entry and self.captcha_token:
            data.update({'logintoken':self.captcha_token, 'logincaptcha':self.captcha_entry})
        err_code, resp = self._get_url_data(AUTH_URL, data)
        if (err_code is not None) and (err_code != 403):
            raise LoginError('unknown', "HTTP Error %d" % (err_code))

        ret_data = self._process_resp(resp)
        if 'Auth' in ret_data:
            self.reset_captcha()
            self.auth_token = ret_data['Auth']
            self._get_rnr_se()
            if self.handle_save_token:
                self.handle_save_token(self)
            return
        if 'Error' not in ret_data:
            raise LoginError('error', 'unknown')
        elif ret_data['Error'] == 'BadAuthentication':
            raise LoginError('failed', 'Invalid Credentials')
        elif ret_data['Error'] == 'CaptchaRequired':
            self.captcha_token = ret_data['CaptchaToken']
            self.captcha_url = CAPTCHA_URL_PREFIX + ret_data['CaptchaUrl']
            self.captcha_entry = None
            if self.handle_captcha_entry and captcha_retry:
                self.handle_captcha_entry(self)
                self._get_auth_token(captcha_retry-1)
            else:
                raise LoginError('captcha', (self.captcha_token, self.captcha_url))
        else:
            raise LoginError('error', ret_data['Error'])

    def _get_account_settings(self):
        if self.account_settings:
            return
        ret = self.get_auth_url(SETTINGS_URL)
        if ret is None:
            return
        self.account_settings = ret[0]

    def reset_captcha(self):
        """
        Resets the state of a captcha locked account so that a new attempt can be tried.

        Use it if you have asked the user to visit the following URL instead of following
        the complete process:
        https://www.google.com/accounts/UnlockCaptcha
        """
        self.captcha_token = None
        self.captcha_url = None
        self.captcha_entry = None

    def unlock_captcha(self, captcha_entry, captcha_token=None):
        """
        Unlocks a captcha locked account using the user/human entered captcha value.
        Call this function after you have got a LoginError exception with e.reason == 'captcha'.
        """
        if captcha_token:
            self.captcha_token = captcha_token
        if not captcha_token:
            raise LoginError('error', 'Captcha not found')
        self.captcha_entry = captcha_entry

    def get_auth_url(self, url, data={}, mode='json', with_retry=True):
        """
        Get a custom URL using the saved ClientLogin token.
        Parameters:
            <url>: The function to be called (Note: Do not include base URL)
            <data>: A dictionary of parameters for the call.
            <mode>: 'raw'|'json'
                'raw' -> Returns the raw result
                'json' -> Attempts to extract JSON return from the page. Otherwise returns None.
            <will_retry>: True|False
                Pass True to allow for a auto-retry in case of missing or expired token. 
        """
        if not self.auth_token:
            self._get_auth_token()
        if url is None:
            return None
        err_code, resp = self._get_url_data(BASE_URL + url, data, {'Authorization': 'GoogleLogin auth=' + self.auth_token})
        if with_retry:
            retry = False
            if (err_code == 401):
                self._get_auth_token()
                retry = True
            elif (err_code == 500):
                self._get_rnr_se()
                if self.handle_save_token:
                    self.handle_save_token(self)
                retry = True
            if retry:
                err_code, resp = self._get_url_data(BASE_URL + url, data, {'Authorization': 'GoogleLogin auth=' + self.auth_token})
        if err_code is not None:
            raise ServerError(err_code, resp)
        if mode != 'json':
            return resp
        res = GET_JSON_RE.search(resp)
        if not res:
            if 'not available in your country' in resp:
                raise LoginError('countryerror', LOGIN_ERR_MSG)
            return None
        if len(res.groups()) == 0:
            return None
        return json.loads(res.groups()[0])

    def get_state(self, mode='full'):
        """
        Returns the state to be saved for later usage of the class.
        
        Parameters:
            <mode>: 'full'|'tokens_only' (default='full')
                'full' -> Returns all arguments for constructor
                'tokens_only' -> Returns only the varaible part, i.e. tokens
        """
        if mode=='full':
            return self.user, self.passwd, self.auth_token, self.rnr_se
        elif mode=='tokens_only':
            return self.auth_token, self.rnr_se

    def validate_credentials(self):
        """
        This just forces the library to get an authentication done so that the
        credentials can be verified and state can be saved.

        Returns: None or raises proper Exception if credentials are invalid
        """
        self.get_auth_url(None)

    def get_numbers(self):
        """
        Fetches the registered phones for the Google Voice account and their properties.

        Returns:
            {num:{attribute:value, ...}, ...}

        Note: the <num> returns as the key for the dictionary is in standard format  and
            will not contain '+' sign before it.

        Hint: ret[num]['verified'] << True or False will show if the number is validated.
        Hint: to force a refresh of account settings, you can do: 
            self.account_settings = None
        """
        self._get_account_settings()
        if not self.account_settings:
            raise LoginError('notinitiated', LOGIN_ERR_MSG)
        ret_dict = {}
        if 'phones' not in self.account_settings:
            self.account_settings['phones'] = {}
        for item in self.account_settings['phones'].values():
            num = item['phoneNumber']
            if num.startswith('+'):
                num = num[1:]
            ret_dict[num] = item
        return ret_dict

    def get_settings(self):
        """
        Fetches the settings of the account and returns them in a dictionary format.
        """
        self._get_account_settings()
        if not self.account_settings:
            return None
        return self.account_settings['settings']

    def call(self, outgoing_number, forwarding_number, phone_type=1, subscriber_number='undefined'):
        """
        Places a call.
        Parameters:
            <outgoing_number>: number to be called
            <fowarding_number>: registered phone number to be called from
            <phone_type>: [optional] type of the destination number

        Returns: True|False
        """
        ret = self.get_auth_url(CALL_URL, {'outgoingNumber': outgoing_number, 'forwardingNumber': forwarding_number,
            'subscriberNumber': subscriber_number, 'phoneType': phone_type, 'remember': '1', '_rnr_se':self.rnr_se}, mode='raw')
        if not ret:
            return False
        try:
            ret = json.loads(ret)
        except ValueError:
            return False
        return ('ok' in ret) and (ret['ok'])

    def cancel(self):
        """
        Cancels the current ongoing call (if one exists).

        Returns: True|False
        """
        ret = self.get_auth_url(CANCEL_URL, {'outgoingNumber': '', 'forwardingNumber': '', 'cancelType':'C2C', 
            '_rnr_se':self.rnr_se}, mode='raw')
        if not ret:
            return False
        try:
           ret = json.loads(ret)
        except ValueError:
            return False
        return ('ok' in ret) and (ret['ok'])

    def edit_forward(self, num_id, enabled):
        if not self.rnr_se:
            _get_rnr_se()
        if enabled:
            enabled=1
        else:
            enabled=0
        self.account_settings = None
        params = {'_rnr_se': self.rnr_se,
            'phoneId':num_id,
            'enabled':enabled}
        ret = self.get_auth_url(EDIT_FORWARD_URL, params, mode='raw')
        if not ret:
            return False, 'Unknown HTTP Error'
        try:
           ret = json.loads(ret)
        except ValueError:
            return False, 'Unknown error'
        if (type(ret) is not dict) or ('ok' not in ret) or (not ret['ok']):
            msg = 'Unable to del number from Google Voice.'
            if (type(ret) is dict) and ('error' in ret):
                msg += ' Reason: %s' % (ret['error'])
            return False, msg
        return True, None

    def del_forward(self, num_id):
        if not self.rnr_se:
            _get_rnr_se()
        self.account_settings = None
        params = {'_rnr_se': self.rnr_se,
            'id':num_id}
        ret = self.get_auth_url(DEL_FORWARD_URL, params, mode='raw')
        if not ret:
            return False, 'Unknown HTTP Error'
        try:
           ret = json.loads(ret)
        except ValueError:
            return False, 'Unknown error'
        if (type(ret) is not dict) or ('ok' not in ret) or (not ret['ok']):
            msg = 'Unable to del number from Google Voice.'
            if (type(ret) is dict) and ('error' in ret):
                msg += ' Reason: %s' % (ret['error'])
            return False, msg
        return True, None

    def get_port_status(self):
        if not self.rnr_se:
            _get_rnr_se()
        self.account_settings = None
        params = {'_rnr_se': self.rnr_se,
            'mid':'1',
            'req':'[]',
            'sid':'8'}
        ret = self.get_auth_url(PORTING_URL, params, mode='raw')
        if not ret:
            return False, 'Unknown HTTP Error'
        ret = ret.replace('[,', '["",')
        ret = ret.replace(',,', ',"",')
        try:
           ret = json.loads(ret)
        except ValueError:
            return False, 'Unknown error'
        try:
            unlocked = (ret[1][0][2][3] != 0)
            paid = (ret[1][0][2][1] != 0)
        except:
            return False, 'Port status unknown'
        return {'unlocked': unlocked, 'paid':paid}
