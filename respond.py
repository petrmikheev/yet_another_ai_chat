import time
import llm, data, web_search, memory

class Debug:
    pass

def _respond(ctx, prompt, short=False, **kwargs):
    actor = ctx.actor
    actor.status = f'{actor.name} is typing'
    grammar = r'root ::= [^.\n]* [\n.]' if short else ''
    response = ctx.ask(f'{prompt} {actor.response_prompt}', prefix=f'{actor.name}:', grammar=grammar, stop=[actor.user + ':'], **kwargs).strip()
    actor.add_record(data.Record(actor.name, response))

def _respond_answer(ctx, logic_ctx=None):
    if len(ctx.last_records) == 0:
        _respond(ctx, f'{ctx.actor.name} should start dialog. Write {ctx.actor.his_her} first message.')
    elif ctx.last_records[-1].header == ctx.actor.name:
        _respond(ctx, f'Continue the previous {ctx.actor.name}\'s response.')
    else:
        _respond(ctx, f'Write {ctx.actor.name}\'s next response.')

def _respond_clarify(ctx, logic_ctx):
    _respond(ctx, f'{ctx.actor.name} considers to ask a clarifying question. Write {ctx.actor.his_her} next response.')
    #_respond(ctx, f'{ctx.actor.name} should ask a clarifying question.', short=True, rep_pen=1.3)

def _finish_search(task):
    actor = task.ctx.actor
    actor.status = f'{actor.name} is typing'
    result = task.result if task.result else task.report
    actor.add_record(data.Record('[WEB SEARCH]', result))
    ctx = create_ctx(actor)
    #_respond(ctx, f'Using WEB SEARCH results write next {actor.name}\'s message to {actor.user} in {actor.his_her} usual communication style.')
    #_respond(ctx, f'Write next {actor.name}\'s response to {actor.user} using all the new information from the WEB SEARCH result.')
    _respond(ctx, f'Rewrite WEB SEARCH result in {actor.name}\'s communication style as {actor.his_her} next response to {actor.user}.')

def _respond_search(ctx, logic_ctx):
    # Double check to reduce probability of false-positive
    if 'No' == ctx.ask(f"Does the context of the dialog requires {ctx.actor.name} to search in internet?", hidden=True, grammar='root ::= "Yes" | "No"'):
        Debug.last_action = 'CANCELLED_SEARCH'
        return _respond_answer(ctx, logic_ctx)
    actor = ctx.actor
    last_msgs = actor.format_records(ctx.last_records[-3:], logic_ctx.model)
    #_respond(ctx, f"{actor.name} will check information online. Write {actor.his_her} initial short response before searching. Don't invent search results.", short=True, temperature=0.2, rep_pen=1.2)
    _respond(ctx, f"{actor.name} will check information online. Write {actor.his_her} initial short response before searching. {actor.He_She} shouldn't provide any facts yet.", short=True, temperature=0.2, rep_pen=1.2)
    if actor.tasks and isinstance(actor.tasks[-1], web_search.SearchTask):
        return
    task = web_search.SearchTask(logic_ctx, last_msgs)
    task.end_handler = _finish_search
    actor.tasks.append(task)

def _respond_task(ctx, logic_ctx):
    actor = ctx.actor
    _respond(ctx, f'Write what {ctx.actor.name} will say before starting the task.', short=True, temperature=0.2)
    task = logic_ctx.ask(f'Formulate {actor.name}\'s task in one line', grammar=r'root ::= [A-Za-z_, 0-9А-Яа-я] [^.\n]* [.\n]', max_token=60)
    print('[Not implemented] TASK:', task)

def _respond_logic(ctx, logic_ctx):
    answer = logic_ctx.ask(f'Solve the task step by step. Use "`" to mark `formules`.', hidden=True)
    _respond(ctx, f'Here is the solution:\n***\n{answer}\n***\nWrite it in {ctx.actor.name}\'s style.')

ANSWER = data.Action('ANSWER', 'If {{char}} can answer right away - ANSWER', _respond_answer)
LOGIC = data.Action('SOLVE_STEP_BY_STEP', 'For a math task - SOLVE_STEP_BY_STEP', _respond_logic)
CLARIFY = data.Action('ASK_DETAILS', 'If the task is unclear and {{char}} needs details - ASK_DETAILS', _respond_clarify)
SEARCH1 = data.Action('SEARCH', 'If the question is about real-world facts - SEARCH in internet', _respond_search)
SEARCH2 = data.Action('WEB_SEARCH', 'If requires actual information or facts - WEB_SEARCH', _respond_search)

# Redirects to ANSWER. Needed to reduce the rate of false-positive classification as SEARCH.
OTHER = data.Action('OTHER', 'If none of the options is applicable - OTHER', _respond_answer)
WEB_SERVICE = data.Action('WEB_SERVICE', 'Service in internet other than search (e.g. translation) - WEB_SERVICE', _respond_answer)

# Not implemented. By the idea it should start a separate thinking loop "plan->action->analyze results" with same interface as web_search.SearchTask.
# Requires additional actions like sandboxed file access for storing temporary data and URL access.
TASK = data.Action('BIG_TASK', 'If the task requires planning or preparations - BIG_TASK', _respond_task)

all_actions = [ANSWER, CLARIFY, SEARCH1, SEARCH2, LOGIC, OTHER]

def create_ctx(actor, timestamp=None, temperature=None, max_token=None):
    last_records = actor.get_last_records(10)
    memory_query = '\n'.join([str(r) for r in last_records[-4:]])
    for i in reversed(range(len(last_records) - 1)):
        if last_records[i+1].time - last_records[i].time > 3600 * 4:
            last_records = last_records[i+1:]
            break
    ctx = data.Context(actor, temperature=temperature, max_token=max_token)
    ctx.last_records = last_records
    ctx.add_default_header()
    current_dialog = f'\n*** CURRENT DIALOG\n\n' + actor.format_records(last_records) + f'\nNow is {actor.time_str(timestamp)}'
    if actor.tasks:
        task = actor.tasks[-1]
        current_dialog += f'\n{task.task_name} is in progress. {task.task_status}'
    memories = memory.get_memories(actor, actor.get_record_count() - len(last_records), query=memory_query, max_size=actor.model.CTX_SIZE - ctx.token_count - actor.model.token_count(current_dialog) - 700, timestamp=timestamp)
    ctx.add(memories)
    ctx.add(current_dialog)
    return ctx

def respond(actor, *, timestamp=None, temperature=None, max_token=None):
    ctx = create_ctx(actor, timestamp=timestamp, temperature=temperature, max_token=max_token)
    actions = actor.respond_actions or [ANSWER]
    if len(actions) == 1 or len(ctx.last_records) == 0:
        Debug.last_action = actions[0].name
        actions[0].fn(ctx)
        return

    logic_ctx = data.Context(actor, llm.logic_model, temperature=0)
    logic_ctx.add_default_header()
    logic_ctx.add(actor.format_records(ctx.last_records, llm.logic_model) + '\n', logging=False)
    logic_ctx.last_records = ctx.last_records

    if actor.tasks and isinstance(actor.tasks[-1], web_search.SearchTask):
        if 'Yes' == logic_ctx.ask(f'Last message was "{ctx.last_records[-1]}". Does the message instruct {actor.name} to give up searching "{actor.tasks[-1].request}"? (Yes/No)', hidden=True, grammar='root ::= "Yes" | "No"'):
            actor.tasks = actor.tasks[:-1]

    if actor.tasks:
        actions = actor.tasks[-1].respond_actions + actions
    action_names = '/'.join(f'{a.name}' for a in actions)
    action_quoted_names = '|'.join(f'"{a.name}"' for a in actions)
    action_descriptions = '\n'.join(a.description for a in actions).replace('{{char}}', actor.name)
    choice = logic_ctx.ask(f'Last message was "{ctx.last_records[-1]}". In response {actor.name} can choose one of the actions:\n{action_descriptions}\nGuess which action {actor.he_she} will use.',
                           grammar=f'root ::= "Since " [A-Za-z_, 0-9А-Яа-я]* ". Action: " ({action_quoted_names})', hidden=True)
    action_name = choice[choice.rfind(' ') + 1:]
    Debug.last_action_reasoning = choice
    Debug.last_action = action_name
    for a in actions:
        if a.name == action_name:
            a.fn(ctx, logic_ctx)
            return
    print('ERROR. Classification failed:', choice)
    ANSWER.fn(ctx, logic_ctx)
