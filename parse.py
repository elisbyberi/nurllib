"""nurllib.parse
urllib.parse is unmaintainable, so this is a clean-slate rewrite of urllib.parse
I am shooting for RFC 3986 compatibility.

(Not necessarily good) ideas:
    - Make URI path a pathlib.Path
    - Support RFC 6874
    - Support RFC 3987
    - Combine _URI and _RELATIVE_REF
"""

import dataclasses
import re

# Each of these ABNF rules is from RFC 3986 or 5234.

# ALPHA = %x41-5A / %x61-7A
_ALPHA: str = r"[A-Za-z]"

# DIGIT =  %x30-39
_DIGIT: str = r"[0-9]"

# HEXDIG = DIGIT / "A" / "B" / "C" / "D" / "E" / "F"
_HEXDIG: str = rf"(?:{_DIGIT}|[A-Fa-f])"

# unreserved = ALPHA / DIGIT / "-" / "." / "_" / "~"
_UNRESERVED: str = rf"(?:{_ALPHA}|{_DIGIT}|[-._~])"

# pct-encoded = "%" HEXDIG HEXDIG
_PCT_ENCODED: str = rf"(?:%{_HEXDIG}{_HEXDIG})"

# sub-delims = "!" / "$" / "&" / "'" / "(" / ")" / "*" / "+" / "," / ";" / "="
_SUB_DELIMS: str = r"(?:[!$&'()*+,;=])"

# pchar = unreserved / pct-encoded / sub-delims / ":" / "@"
_PCHAR: str = rf"(?:{_UNRESERVED}|{_PCT_ENCODED}|{_SUB_DELIMS}|[:@])"

# query = *( pchar / "/" / "?" )
_QUERY: str = rf"(?P<query>(?:{_PCHAR}|[/?])*)"

# fragment = *( pchar / "/" / "?" )
_FRAGMENT: str = rf"(?P<fragment>(?:{_PCHAR}|[/?])*)"

# scheme = ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
_SCHEME: str = rf"(?P<scheme>{_ALPHA}(?:{_ALPHA}|{_DIGIT}|[+\-.])*)"

# segment = *pchar
_SEGMENT: str = rf"{_PCHAR}*"

# segment-nz = 1*pchar
_SEGMENT_NZ: str = rf"{_PCHAR}+"

# segment-nz-nc = 1*( unreserved / pct-encoded / sub-delims / "@" )
_SEGMENT_NZ_NC: str = rf"(?:(?:{_UNRESERVED}|{_PCT_ENCODED}|{_SUB_DELIMS}|@)+)"

# path-absolute = "/" [ segment-nz *( "/" segment ) ]
_PATH_ABSOLUTE: str = rf"(?P<path_absolute>/(?:{_SEGMENT_NZ}(?:/{_SEGMENT})*)?)"

# path-empty = 0<pchar>
_PATH_EMPTY: str = r"(?P<path_empty>)"

# path-rootless = segment-nz *( "/" segment )
_PATH_ROOTLESS: str = rf"(?P<path_rootless>{_SEGMENT_NZ}(?:/{_SEGMENT})*)"

# path-abempty = *( "/" segment )
_PATH_ABEMPTY: str = rf"(?P<path_abempty>(?:/{_SEGMENT})*)"

# path-noscheme = segment-nz-nc *( "/" segment )
_PATH_NOSCHEME: str = rf"(?P<path_noscheme>{_SEGMENT_NZ_NC}(?:/{_SEGMENT})*)"

# userinfo = *( unreserved / pct-encoded / sub-delims / ":" )
_USERINFO: str = rf"(?P<userinfo>(?:{_UNRESERVED}|{_PCT_ENCODED}|{_SUB_DELIMS}|:)*)"

# dec-octet = DIGIT / %x31-39 DIGIT / "1" 2DIGIT / "2" %x30-34 DIGIT / "25" %x30-35
_DEC_OCTET: str = rf"(?:{_DIGIT}|[1-9]{_DIGIT}|1{_DIGIT}{{2}}|2[0-4]{_DIGIT}|25[0-5])"

# IPv4address = dec-octet "." dec-octet "." dec-octet "." dec-octet
_IPV4ADDRESS: str = rf"(?:{_DEC_OCTET}\.{_DEC_OCTET}\.{_DEC_OCTET}\.{_DEC_OCTET})"

# h16 = 1*4HEXDIG
_H16: str = r"(?:[0-9A-F]{1,4})"

# ls32 = ( h16 ":" h16 ) / IPv4address
_LS32: str = rf"(?:{_H16}:{_H16}|{_IPV4ADDRESS})"

# IPv6address =                            6( h16 ":" ) ls32
#                       /                       "::" 5( h16 ":" ) ls32
#                       / [               h16 ] "::" 4( h16 ":" ) ls32
#                       / [ *1( h16 ":" ) h16 ] "::" 3( h16 ":" ) ls32
#                       / [ *2( h16 ":" ) h16 ] "::" 2( h16 ":" ) ls32
#                       / [ *3( h16 ":" ) h16 ] "::"    h16 ":"   ls32
#                       / [ *4( h16 ":" ) h16 ] "::"              ls32
#                       / [ *5( h16 ":" ) h16 ] "::"              h16
#                       / [ *6( h16 ":" ) h16 ] "::"
_IPV6ADDRESS: str = (
    "(?:"
    + r"|".join(
        (
                                           rf"(?:{_H16}:){{6}}{_LS32}",
                                         rf"::(?:{_H16}:){{5}}{_LS32}",
                              rf"(?:{_H16})?::(?:{_H16}:){{4}}{_LS32}",
            rf"(?:(?:{_H16}:){{0,1}}{_H16})?::(?:{_H16}:){{3}}{_LS32}",
            rf"(?:(?:{_H16}:){{0,2}}{_H16})?::(?:{_H16}:){{2}}{_LS32}",
            rf"(?:(?:{_H16}:){{0,3}}{_H16})?::(?:{_H16}:){{1}}{_LS32}",
            rf"(?:(?:{_H16}:){{0,4}}{_H16})?::{_LS32}",
            rf"(?:(?:{_H16}:){{0,5}}{_H16})?::{_H16}",
            rf"(?:(?:{_H16}:){{0,6}}{_H16})?::",
        )
    )
    + ")"
)

# IPvFuture = "v" 1*HEXDIG "." 1*( unreserved / sub-delims / ":" )
_IPVFUTURE: str = rf"(?:v{_HEXDIG}+\.(?:{_UNRESERVED}|{_SUB_DELIMS}|:)+)"

# IP-literal = "[" ( IPv6address / IPvFuture  ) "]"
_IP_LITERAL: str = rf"(?:\[(?:{_IPV6ADDRESS}|{_IPVFUTURE})\])"

# reg-name = *( unreserved / pct-encoded / sub-delims )
_REG_NAME: str = rf"(?:(?:{_UNRESERVED}|{_PCT_ENCODED}|{_SUB_DELIMS})*)"

# host = IP-literal / IPv4address / reg-name
_HOST: str = rf"(?P<host>{_IP_LITERAL}|{_IPV4ADDRESS}|{_REG_NAME})"

# port = *DIGIT
_PORT: str = rf"(?P<port>{_DIGIT}*)"

# authority = [ userinfo "@" ] host [ ":" port ]
_AUTHORITY: str = rf"(?:(?:{_USERINFO}@)?{_HOST}(?::{_PORT})?)"

# hier-part = "//" authority path-abempty / path-absolute / path-rootless / path-empty
_HIER_PART: str = (
    rf"(?://{_AUTHORITY}{_PATH_ABEMPTY}|{_PATH_ABSOLUTE}|{_PATH_ROOTLESS}|{_PATH_EMPTY})"
)

# URI = scheme ":" hier-part [ "?" query ] [ "#" fragment ]
_URI: str = rf"\A{_SCHEME}:{_HIER_PART}(?:\?{_QUERY})?(?:#{_FRAGMENT})?\Z"

# relative-part = "//" authority path-abempty / path-absolute / path-noscheme / path-empty
_RELATIVE_PART: str = rf"(?://{_AUTHORITY}{_PATH_ABEMPTY}|{_PATH_ABSOLUTE}|{_PATH_NOSCHEME}|{_PATH_EMPTY})"

# relative-ref  = relative-part [ "?" query ] [ "#" fragment ]
_RELATIVE_REF: str = rf"\A{_RELATIVE_PART}(?:\?{_QUERY})?(?:#{_FRAGMENT})?\Z"

@dataclasses.dataclass
class URLParseResult:
    """A class to hold a URI reference.
    Counterpart to urllib's ParseResult and ParseResultBytes.
    """
    scheme: str | None
    userinfo: str | None
    host: str | None
    port: int | None
    path: str
    query: str | None
    fragment: str | None

    def __getitem__(self, idx: int):
        """urllib compatibility function. The old ParseResult was a namedtuple, so this is here to maintain compatibility with it.
        """
        match idx:
            case 0:
                return self.scheme
            case 1:
                return self.netloc
            case 2:
                return self.path
            case 3:
                return self.params
            case 4:
                return self.query
            case 5:
                return self.fragment
            case _:
                raise IndexError("index out of range")

    def geturl(self) -> str:
        result: str = ""
        if scheme is not None:
            result += scheme + ":"
        if userinfo is not None:
            result += userinfo + "@"
        if host is not None:
            result += host
        if port is not None:
            result += ":" + str(port)
        result += path
        if query is not None:
            result += "?" + query
        if fragment is not None:
            result += "#" + fragment
        return result

    @property
    def hostname(self) -> str:
        """Only here for urllib compatibility. Returns self.host."""
        return self.host

    @property
    def netloc(self) -> str:
        """Only here for urllib compatibility. Returns username@host:port separated by a colon."""
        result: str = ""
        if self.userinfo is not None:
            result += self.userinfo + "@"
        if self.host is not None:
            result += self.host
        if self.port is not None:
            result += ":" + str(self.port)
        return result

    @property
    def params(self) -> str:
        """Only here for urllib compatibility. Returns everything after the first semicolon in the last path segment."""
        _, _, last_seg = self.path.rpartition("/")
        _, _, result = last_seg.rpartition(";")
        return result

    @property
    def password(self) -> str:
        """Only here for urllib compatibility. Returns everything after the first colon in the userinfo."""
        colon_idx: int = userinfo.find(":")
        if colon_idx == -1:
            return None
        return self.userinfo[colon_index + 1:]

def urlparse(url: str, scheme: str | None = None) -> URLParseResult:
    """The URL parser.
    Changes from urllib:
        - No allow_fragments parameter.
    """

    if uri_match := re.match(_URI, url):
        uri_scheme: str = uri_match["scheme"]
        uri_userinfo: str | None = uri_match["userinfo"]
        uri_host: str | None = uri_match["host"]
        uri_port_str: str | None = uri_match["port"]
        uri_port: int | None = int(uri_port_str) if uri_port_str else None
        uri_path: str = uri_match["path_abempty"] or uri_match["path_absolute"] or uri_match["path_rootless"] or uri_match["path_empty"]
        uri_query: str | None = uri_match["query"]
        uri_fragment: str | None = uri_match["fragment"]

        return URLParseResult(
                scheme=uri_scheme,
                userinfo=uri_userinfo,
                host=uri_host,
                port=uri_port,
                path=uri_path,
                query=uri_query,
                fragment=uri_fragment,
            )
    elif rr_match := re.match(_RELATIVE_REF, url):
        rr_userinfo: str | None = rr_match["userinfo"]
        rr_host: str | None = rr_match["host"]
        rr_port_str: str | None = rr_match["port"]
        rr_port: int | None = int(rr_port_str) if rr_port_str else None
        rr_path: str = rr_match["path_abempty"] or rr_match["path_absolute"] or rr_match["path_noscheme"] or rr_match["path_empty"]
        rr_query: str | None = rr_match["query"]
        rr_fragment: str | None = rr_match["fragment"]

        return URLParseResult(
                scheme=scheme,
                userinfo=rr_userinfo,
                host=rr_host,
                port=rr_port,
                path=rr_path,
                query=rr_query,
                fragment=rr_fragment,
            )
    else:
        raise ValueError("failed to parse URL.")
