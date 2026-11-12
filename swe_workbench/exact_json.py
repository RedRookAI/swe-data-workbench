"""Versioned exact JSON observation trees; legacy canonical JSON stays unchanged."""
import json,re,sys
from .errors import WorkbenchError
from .intake import MAX_RECORDS

FORMAT='swe-workbench-exact-json/v1'
TOKEN_LIMIT=sys.int_info.default_max_str_digits  # Existing Python default integer-input guard.
NUMBER=re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
class Token(str):pass

def number(text):
    if len(text)>TOKEN_LIMIT or not NUMBER.fullmatch(text):raise WorkbenchError('exact-number','Numeric token exceeds the supported Python input guard or has invalid JSON syntax.')
    return Token(text)

def decode(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def reject(value):raise ValueError('Nonfinite JSON number')
    try:
        value=json.loads(text,parse_float=number,parse_int=number,parse_constant=reject,object_pairs_hook=pairs)
        # Traverse once for bounded depth/nodes, valid Unicode and explicit types.
        encode(value)
        return value
    except (ValueError,UnicodeError,RecursionError) as error:raise WorkbenchError('exact-json','Expected bounded unambiguous UTF-8 JSON.') from error

def encode(value):
    nodes=0
    def visit(item,depth=0):
        nonlocal nodes
        nodes+=1
        if depth>128 or nodes>MAX_RECORDS:raise WorkbenchError('exact-json','Exact observation nesting/node limit exceeded.')
        if item is None:return {'type':'null'}
        if isinstance(item,Token):return {'type':'number','token':str(item)}
        if isinstance(item,bool):return {'type':'boolean','value':item}
        if isinstance(item,str):
            item.encode('utf-8');return {'type':'string','value':item}
        if isinstance(item,list):return {'type':'array','items':[visit(x,depth+1) for x in item]}
        if isinstance(item,dict):
            for key in item:key.encode('utf-8')
            return {'type':'object','members':{k:visit(v,depth+1) for k,v in item.items()}}
        raise WorkbenchError('exact-json','Unsupported exact observation type.')
    return visit(value)

def meaning(token):
    token=number(token);m=re.fullmatch(r'(-?)([0-9]+)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?',token)
    kind='decimal' if '.' in token or 'e' in token.lower() else 'integer';digits=(m[2]+(m[3] or '')).lstrip('0');exponent=int(m[4] or '0')-len(m[3] or '')
    if not digits:return (kind,m[1] if kind=='decimal' else '', '0',0)
    trim=len(digits)-len(digits.rstrip('0'));return (kind,m[1],digits.rstrip('0'),exponent+trim)
