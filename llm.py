import requests, re

def _json(r):
    if r.status_code != 200:
        raise Exception(f'HTTP status {r.status_code}')
    return r.json()

class Model:
    def __init__(self, addr, user, model, *, system='', end='\n', ctx_size=4096, stop=[]):
        self.addr = addr  # llama.cpp server url
        self.USER = user
        self.MODEL = model
        self.SYS = system
        self.END = end
        self.CTX_SIZE = ctx_size
        self.stop = stop
        self._re_special = re.compile('|'.join([re.escape(x.strip()) for x in [user, model, system, end] if x.strip()]))
        self._token_count_cache = {}

    def remove_special(self, s):
        return self._re_special.sub('', s)

    def format(self, role, msg):
        if self.SYS:
            return role + msg + self.END
        else:
            return msg + self.END

    def tokenize(self, content):
        return _json(requests.post(self.addr + '/tokenize', json={'content' : content}))['tokens']

    def detokenize(self, tokens):
        return _json(requests.post(self.addr + '/detokenize', json={'tokens' : tokens}))['content']

    def token_count(self, content):
        h = hash(content)
        if h in self._token_count_cache:
            return self._token_count_cache[h]
        else:
            res = len(self.tokenize(content))
            self._token_count_cache[h] = res
            return res
    
    def get_embedding(self, content):
        return _json(requests.post(self.addr + '/embedding', json={'content' : content}))['embedding']
    
    def generate(self, prompt, *, max_token=500, temperature=0.6, grammar='', rep_pen=1.1, rep_pen_range=-1, stop=[]):
        args = {
            'prompt': prompt,
            'n_predict': max_token,
            'temperature': temperature,
            'repeat_penalty': rep_pen,
            'repeat_last_n': rep_pen_range,
            'stop': stop + self.stop,
        }
        if grammar:
            args['grammar'] = grammar
        res = _json(requests.post(self.addr + '/completion', json=args))
        content = res['content']
        if res['stopped_limit']:
            sp = max(content.rfind(' '), content.rfind('\n'))
            if sp > 0: content = content[:sp]
        return content
    
    def ask(self, ctx, question, prefix='', **kwargs):
        if question:
            prompt = f'{self.SYS or self.USER}{question}{self.END}{self.MODEL}{prefix}'
        else:
            prompt = self.MODEL + prefix
        res = self.generate(ctx + prompt, **kwargs).strip()
        return res, prompt

models = {
    #'pygmalion': Model('http://127.0.0.1:8081', '<|user|>', '<|model|>', system='<|system|>', stop=['<|']),
    'mythomax': Model('http://127.0.0.1:8081', '### Instruction:\n', '### Response:\n'),
    #'wizardlm': Model('http://127.0.0.1:8080', 'USER:\n', 'ASSISTANT:\n'),
    'openchat': Model('http://127.0.0.1:8080', 'GPT4 User:', 'GPT4 Assistant:', end='<|end_of_turn|>', ctx_size=8192),
    'openchat_code': Model('http://127.0.0.1:8080', 'Code User:', 'Code Assistant:', end='<|end_of_turn|>', ctx_size=8192),
}

logic_model = models['openchat']
role_play_model = models['mythomax']
