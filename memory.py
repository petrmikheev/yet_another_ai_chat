import time, math
import llm, data

def get_memories(actor, end_id, query, max_size, timestamp=None):
    if end_id <= 0: return ''
    if timestamp is None: timestamp = time.time()
    query_embeddings=llm.logic_model.get_embedding(query)
    db_size = actor.db.count()
    new_memories = actor.db.query(query_embeddings=query_embeddings,
                                  where={"$and": [ {"id": {"$lt": end_id}}, {"id": {"$gte": end_id-100}} ]}, n_results=min(100, db_size))
    distances = new_memories['distances'][0]
    metadatas = new_memories['metadatas'][0]
    if db_size > 100:
        old_memories = actor.db.query(query_embeddings=query_embeddings, where={"id": {"$lt": end_id-100}}, n_results=100)
        distances = old_memories['distances'][0] + distances
        metadatas = old_memories['metadatas'][0] + metadatas
    if len(distances) == 0: return ''
    min_dist, max_dist = min(distances), max(distances)
    def score(d, m):
        time_score = math.exp((m['time'] - timestamp) / (3600.0 * 24))
        dist_score = (d - min_dist) / (max_dist - min_dist + 1.0e-10)
        return dist_score - time_score
    sorted_candidates = sorted([(score(d, m), m) for d, m in zip(distances, metadatas)])
    chosen = {}
    for _, m in sorted_candidates:
        id = m['id']
        ids = [x for x in range(max(0, id - m['context_size'] + 1), id + 1) if x not in chosen]
        if len(ids) == 0: continue
        records = actor.get_records(ids)
        token_count = sum([actor.model.token_count(str(r)) for r in records]) + 1
        if token_count > max_size: break
        max_size -= token_count
        for i, r in zip(ids, records):
            chosen[i] = r
    last_id = None
    last_time = 0
    res = ''
    for id in sorted(chosen):
        r = chosen[id]
        if r.time - last_time > 3600 * 4:
            if res:
                res += f'\n*** MEMORIES {actor.time_str(r.time)}\n\n'
            else:
                res += f'*** MEMORIES {actor.time_str(r.time)}\n\n'
        elif id > last_id + 1:
            res += '***\n'
        res += f'{r}\n'
        last_time = r.time
        last_id = id
    return res
