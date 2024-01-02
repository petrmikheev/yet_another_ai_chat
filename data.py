import time
import llm

class Record:
    def __init__(self, header, content, *, timestamp=None, context_size=4):
        self.header = header
        self.content = content
        self.time = timestamp or time.time()
        self.context_size = context_size

    def __str__(self):
        return f'{self.header}: {self.content}'

    def __repr__(self):
        return str(self)

class Action:
    def __init__(self, name, description, fn):
        self.name = name
        self.description = description
        self.fn = fn

class Actor:
    def __init__(self, db, name, is_female=True, user='User'):
        if not db.metadata or 'size' not in db.metadata:
            metadata = db.metadata or {}
            metadata['size'] = 0
            db.modify(metadata=metadata)
        self.db = db
        self.name = name
        self.is_female = is_female
        self.user = user
        self.He_She = 'She' if is_female else 'He'
        self.His_Her = 'Her' if is_female else 'His'
        self.he_she = self.He_She.lower()
        self.his_her = self.His_Her.lower()
        self.character = ''
        self.log = ''
        self.response_prompt = ''
        self.examples = []
        self.respond_actions = []
        self.model = llm.role_play_model
        self.status = ''
        self.tz_offset = 0
        self.respond_requested = False
        self.incoming_records = []
        self.tasks = []

    def time_str(self, timestamp=None):
        tz = int(self.tz_offset / 3600 + 11) % 24 - 11
        return time.asctime(time.gmtime((timestamp or time.time()) + self.tz_offset)) + f' UTC{tz:+}'
    
    def get_record_count(self):
        return self.db.metadata['size']

    def get_records(self, ids):
        if len(ids) == 0: return []
        res = self.db.get(ids=[str(id) for id in ids], include=["metadatas"])
        res = sorted(zip([int(i) for i in res['ids']], res['metadatas']))
        return [Record(d['header'], d['content'], timestamp=d['time']) for _, d in res]

    def get_last_records(self, count):
        size = self.get_record_count()
        return self.get_records(range(max(size - count, 0), size))

    def add_record(self, rec):
        id = self.db.metadata['size']
        recs = [rec]
        if rec.context_size > 1:
            recs = self.get_records(range(max(0, id-rec.context_size+1), id)) + recs
        embedding = llm.logic_model.get_embedding('\n'.join([str(r) for r in recs]))
        self.db.add(ids=str(id), embeddings=embedding, metadatas={
            'id': id,
            'header': rec.header,
            'content': rec.content,
            'time': rec.time,
            'context_size': rec.context_size,
        })
        self.db.metadata['size'] = id + 1
        self.db.modify(metadata=self.db.metadata)

    def shrink_records(self, new_size):
        size = self.db.metadata['size']
        if new_size >= size: return
        self.db.delete(ids=[str(id) for id in range(new_size, size)])
        self.db.metadata['size'] = new_size
        self.db.modify(metadata=self.db.metadata)

    def append_log(self, msg, prefix=''):
        if msg.endswith('\n'): msg = msg[:-1]
        if prefix:
            self.log += '\n'.join([prefix + s for s in msg.split('\n')]) + '\n'
        else:
            self.log += msg + '\n'

    def format_persona(self, with_examples=True):
        res = f"{self.character.strip()}\n"
        if with_examples and self.examples and self.get_record_count() < 20:
            res += '\n*** EXAMPLES (not related to the current dialog)\n<START>\n' + '\n<START>\n'.join(self.examples) + '\n*** EXAMPLES END\n'
        return res

    def format_records(self, records, model=None):
        if not records: return ''
        if model is None: model = self.model
        def role(r):
            if r.header == self.name: return model.MODEL
            elif r.header.startswith('['): return model.SYS
            else: return model.USER
        return ''.join([model.format(role(r), str(r)) for r in records])

class Context:
    def __init__(self, actor, model=None, *, temperature=None, max_token=None):
        self.model = model or actor.model
        self.temperature = temperature
        self.max_token = max_token
        self.actor = actor
        self.ctx = ''
        self.token_count = 0
        self.ctx_stack = []

    def add(self, str, logging=True):
        if logging: self.actor.append_log(str)
        self.ctx += str
        self.token_count += self.model.token_count(str)

    def add_default_header(self):
        if self.model == llm.role_play_model:
            prompt = f'Enter RP mode. Act as {self.actor.name}.\n{self.actor.format_persona()}'
        else:
            prompt = self.actor.format_persona(with_examples=False)
        self.add(self.model.format(self.model.SYS, prompt), logging=False)

    def ask(self, question, *, hidden=False, **kwargs):
        if self.temperature is not None:
            if 'temperature' in kwargs:
                kwargs['temperature'] = min(self.temperature, kwargs['temperature'])
            else:
                kwargs['temperature'] = self.temperature
        if self.max_token is not None:
            if 'max_token' in kwargs:
                kwargs['max_token'] = min(self.max_token, kwargs['max_token'])
            else:
                kwargs['max_token'] = self.max_token
        res, prompt = self.model.ask(self.ctx, question, **kwargs)
        if hidden:
            self.actor.append_log(prompt + res, prefix='   | ')
        else:
            self.actor.append_log(prompt + res)
            self.ctx += prompt + res + self.model.END
        return res

    def push_state(self):
        self.ctx_stack.append((self.ctx, self.token_count))

    def pop_state(self):
        self.ctx, self.token_count = self.ctx_stack[-1]
        del self.ctx_stack[-1]
