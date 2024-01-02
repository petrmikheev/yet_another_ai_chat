import chromadb, json, time
import respond

temp_db = chromadb.EphemeralClient()

def get_test_db(path):
    return chromadb.PersistentClient(path, settings=chromadb.config.Settings(anonymized_telemetry=False, allow_reset=True))

def copy_collection(collection, db, name):
    new_collection = db.create_collection(name, dict(collection.metadata, orig=collection.name, copy_time=time.time()))
    data = collection.get(include=["embeddings", "metadatas"])
    new_collection.add(ids=data['ids'], embeddings=data['embeddings'], metadatas=data['metadatas'])
    return new_collection

def temp_actor(collection, actor_templates, temp_id=0):
    try:
        temp_db.delete_collection(f'temp_actor{temp_id}')
    except:
        pass
    temp_collection = copy_collection(collection, temp_db, f'temp_actor{temp_id}')
    template = actor_templates[collection.metadata['template']]
    return template(temp_collection, **json.loads(collection.metadata['args']))

def try_respond(actor, *, max_token=None):
    tasks = actor.tasks.copy()
    rc = actor.get_record_count()
    last_records = actor.get_last_records(4)
    timestamp = last_records[-1].time if last_records else 0
    respond.respond(actor, timestamp=timestamp, temperature=0, max_token=max_token)
    if actor.get_record_count() != rc + 1:
        print(f'ERROR at id={rc}')
    actor.tasks = tasks
    return {
        'id': rc,
        'context': '\n'.join('   ' + str(x)[:80] for x in last_records),
        'action': respond.Debug.last_action,
        'action_reasoning': respond.Debug.last_action_reasoning,
        'response': str(actor.get_last_records(1)[0])
    }

def try_respond_all(actor, *, max_token=None):
    records = actor.get_records(range(actor.get_record_count()))
    results = []
    for i in reversed(range(len(records))):
        if records[i].header != actor.user:
            continue
        actor.shrink_records(i + 1)
        results = [try_respond(actor, max_token=max_token)] + results
    return results

def diff(collection, res, reasoning=True, response=True, resp_len=80):
    if type(res) == list:
        for r in res:
            diff(collection, r, reasoning, response)
        return
    meta = collection.get(str(res['id']))['metadatas'][0]
    diff_action = res['action'] != meta['ref_action'] or (res['action_reasoning'] != meta['ref_action_reasoning'] and reasoning)
    resp_ref = meta['ref_response'][:resp_len]
    resp_new = res['response'][:resp_len]
    diff_resp = response and resp_new != resp_ref
    if not diff_action and not diff_resp:
        return
    print(f'********* {collection.name} {res["id"]}\n{res["context"]}\n')
    if diff_action:
        print(f"ACTION REF: {meta['ref_action']} | {meta['ref_action_reasoning']}")
        print(f"ACTION NEW: {res['action']} | {res['action_reasoning']}")
    else:
        print(f"ACTION (no diff): {res['action']} | {res['action_reasoning']}")
    if resp_new != resp_ref and (response or res['action'] != meta['ref_action']):
        print(f"MSG REF: {resp_ref}")
        print(f"MSG NEW: {resp_new}")
    print()

def update_reference(collection, refs):
    refs_dict = {str(r['id']): r for r in refs}
    data = collection.get(ids=list(refs_dict), include=["metadatas"])
    ids = data['ids']
    metas = data['metadatas']
    for i in range(len(ids)):
        meta = metas[i]
        ref = refs_dict[ids[i]]
        meta['ref_action'] = ref['action']
        meta['ref_action_reasoning'] = ref['action_reasoning']
        meta['ref_response'] = ref['response']
    collection.update(ids=ids, metadatas=metas)

def clone_for_test(path, actor_templates, collections):
    test_db = get_test_db(path)
    for prod_col in collections:
        print(prod_col.name)
        try:
            actor = temp_actor(prod_col, actor_templates)
        except:
            print('   SKIP')
            continue
        refs = try_respond_all(actor)
        test_col = copy_collection(prod_col, test_db, prod_col.name)
        update_reference(test_col, refs)
        print(f'   OK ({len(refs)} responses)')
