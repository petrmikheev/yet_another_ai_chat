import flask
import json
import time
import threading
import chromadb
import random
import string
import traceback

import data, respond

try:
    from users import users, public_access, public_access_templates
except:
    print('Create "users.py" with a dict from userkey to allowed actor templates.')
    print('Userkey for testing is "testuserkey00000".')
    import actors as actor_templates
    users = {
        'testuserkey00000': actor_templates.all,
    }
    public_access = False
    public_access_templates = actor_templates.all

actors = {}

app = flask.Flask(__name__)

db = chromadb.HttpClient(host='localhost', port=8000, settings=chromadb.config.Settings(anonymized_telemetry=False))

def validate_user_key(key):
    if len(key) != 16:
        raise Exception('Invalid userkey')
    for c in key:
        if c not in string.ascii_letters and c not in string.digits:
            raise Exception('Invalid userkey')
    if public_access or key in users:
        return key
    else:
        raise Exception('Invalid userkey')

def get_templates(userkey):
    if userkey in users:
        return users[userkey]
    elif public_access:
        return public_access_templates
    else:
        return {}

def get_actor(args):
    user_key = validate_user_key(args['userkey'])
    chat_id = args['chatid']
    actor_id = user_key + '_' + chat_id
    if actor_id not in actors:
        collection = db.get_collection(actor_id)
        if 'deleted' in collection.metadata:
            raise Exception('Deleted')
        template = get_templates(user_key)[collection.metadata['template']]
        actors[actor_id] = template(collection, **json.loads(collection.metadata['args']))
    return actors[actor_id]

def random_identifier(n):
    return ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(n))

def prepare_records(actor, rfrom, rto=None):
    size = actor.get_record_count()
    if rto is None: rto = size
    if rfrom < 0: rfrom = max(rfrom + size, 0)
    if rto < 0: rto = max(rto + size, 0)
    records = actor.get_records(range(rfrom, rto))
    rto = rfrom + len(records)
    return [{
        'id': i,
        'time': records[i - rfrom].time,
        'role': records[i - rfrom].header,
        'content': records[i - rto].content,
    } for i in range(rfrom, rto)]

def prepare_draft_records(actor):
    return [{
        'time': r.time,
        'role': r.header,
        'content': r.content,
    } for r in actor.incoming_records]

def handle_actor(actor):
    if actor.respond_requested:
        actor.status = f'{actor.name} is typing'
        actor.respond_requested = False
        try:
            respond.respond(actor)
            print(actor.log)
        except:
            print(actor.log)
            traceback.print_exc()
        actor.log = ''
        actor.status = actor.tasks[-1].task_status if actor.tasks else ''
    elif actor.tasks:
        task = actor.tasks[-1]
        try:
            if not task.next_action():
                actor.status = ''
                actor.tasks = actor.tasks[:-1]
                if task.end_handler:
                    task.end_handler(task)
            print(actor.log)
        except:
            print(actor.log)
            traceback.print_exc()
        actor.status = actor.tasks[-1].task_status if actor.tasks else ''
        actor.log = ''

def worker():
    low_priority_queue = []
    while True:
        renew_queue = len(low_priority_queue) == 0
        for actor_id, actor in actors.copy().items():
            if actor.incoming_records:
                new_records = actor.incoming_records
                actor.incoming_records = []
                for r in new_records:
                    actor.add_record(r)
                actor.respond_requested = True
            if not actor.respond_requested and not actor.tasks or actor_id not in actors:
                continue
            user_key = actor_id.split('_')[0]
            if user_key in users:  # know users have priority
                handle_actor(actor)
                time.sleep(0)
            elif renew_queue:  # unknown users (possible if public_access=True) have low priority
                low_priority_queue.append(actor_id)
        if low_priority_queue:
            actor_id = low_priority_queue[0]
            low_priority_queue = low_priority_queue[1:]
            if actor_id in actors:
                handle_actor(actors[actor_id])
        time.sleep(0)

def chat_title(chat_id, template, chat_args):
    if 'char' in chat_args:
        return f"{chat_args['char']} ({template}, {chat_id})"
    else:
        return f"{template} ({chat_id})"

@app.route('/')
def request_index():
    return flask.render_template('index.html')

@app.route('/user', methods=['POST'])
def request_user():
    args = json.loads(flask.request.data)
    try:
        user_key = validate_user_key(args['userkey'])
    except:
        print('Invalid user key:', args['userkey'])
        return json.dumps({'ok': False})
    try:
        prefix = user_key + '_'
        chats = {}
        for x in db.list_collections():
            if x.name.startswith(prefix) and 'deleted' not in x.metadata:
                chat_id = x.name[len(prefix):]
                chats[chat_id] = chat_title(chat_id, x.metadata['template'], json.loads(x.metadata['args']))
        data = {
            'ok': True,
            'chats': chats,
            'templates': {key: x.spec for key, x in get_templates(user_key).items()}
        }
    except:
        traceback.print_exc()
        data = {'ok': False}
    return json.dumps(data)

@app.route('/check_public_access', methods=['GET', 'POST'])
def request_check_public_access():
    if public_access:
        key = random_identifier(16)
        while key in users:
            key = random_identifier(16)
        return json.dumps({
            'allowed': True,
            'suggested_key': key,
        })
    else:
        return json.dumps({
            'allowed': False,
        })

@app.route('/new_chat', methods=['POST'])
def request_new_chat():
    args = json.loads(flask.request.data)
    user_key = validate_user_key(args['userkey'])
    template_key = args['template']
    factory_args = args['args']
    templates = get_templates(user_key)
    if template_key not in templates:
        raise Exception('Invalid template')
    chat_id = random_identifier(16)
    actor_id = user_key + '_' + chat_id
    db.create_collection(actor_id, metadata={
        "hnsw:space": "cosine",
        "template": template_key,
        "args": json.dumps(factory_args),
    })
    return json.dumps({
        'new_chat': chat_id,
        'chat_title': chat_title(chat_id, template_key, factory_args),
    })

@app.route('/copy_chat', methods=['POST'])
def request_copy_chat():
    args = json.loads(flask.request.data)
    actor = get_actor(args)
    new_chat_id = random_identifier(16)
    new_actor_id = args['userkey'] + '_' + new_chat_id
    new_collection = db.create_collection(name, metadata=actor.db.metadata)
    data = actor.db.get(include=["embeddings", "metadatas"])
    new_collection.update(ids=data['ids'], embeddings=data['embeddings'], metadatas=data['metadatas'])
    return json.dumps({'new_chat', new_chat_id})

@app.route('/delete_chat', methods=['POST'])
def request_delete_chat():
    args = json.loads(flask.request.data)
    actor = get_actor(args)
    del actors[actor.db.name]
    actor.db.metadata['deleted'] = True
    actor.db.modify(metadata=actor.db.metadata)
    if actor.get_record_count() < 10:
        db.delete_collection(actor.db.name)
    return ''

@app.route('/get_chat', methods=['POST'])
def request_get_chat():
    args = json.loads(flask.request.data)
    actor = get_actor(args)
    data = {
        'user': actor.user,
        'char': actor.name,
        'records': prepare_records(actor, args['from'] if 'from' in args else -30, args['to'] if 'to' in args else None),
        'draft_records': prepare_draft_records(actor),
        'status': actor.status or (f'{actor.name} is typing' if actor.respond_requested else ''),
        'template': actor.db.metadata['template'],
        'template_args': json.loads(actor.db.metadata['args']),
    }
    return json.dumps(data)

@app.route('/remove_last', methods=['POST'])
def request_remove_last():
    args = json.loads(flask.request.data)
    actor = get_actor(args)
    actor.shrink_records(args['new_end'])
    return ''

@app.route('/add', methods=['POST'])
def request_add():
    args = json.loads(flask.request.data)
    actor = get_actor(args)
    actor.tz_offset = args['tz_offset']
    if 'content' in args and args['content']:
        actor.incoming_records.append(data.Record(args['role'], args['content']))
    actor.respond_requested = True
    return ''

if __name__ == "__main__":
    w = threading.Thread(target=worker)
    w.daemon = True
    w.start()
    app.run(host='0.0.0.0')
