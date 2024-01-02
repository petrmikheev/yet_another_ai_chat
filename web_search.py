import re
import requests
import time
from duckduckgo_search import DDGS
from html.parser import HTMLParser

import data, llm

class _MinimalHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.is_head = False
        self.is_script = False
        self.data = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'head': self.is_head = True
        if tag == 'script': self.is_script = True

    def handle_endtag(self, tag):
        if tag == 'head': self.is_head = False
        if tag == 'script': self.is_script = False

    def handle_data(self, data):
        if self.is_head or self.is_script: return
        data = data.strip()
        if data:
            self.data.append(data)

class _Cache:
    def __init__(self, tl=7200):
        self.tl = tl
        self.cache = {}

    def get(self, key):
        if key not in self.cache:
            return None
        t, res = self.cache[key]
        if time.time() - t < self.tl:
            return res
        else:
            return None

    def set(self, key, value):
        self.cache[key] = (time.time(), value)

_headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0'}
_search_cache = _Cache()
_load_page_cache = _Cache()

def load_page_content(url):
    text = _load_page_cache.get(url)
    if text is None:
        print('Downloading', url)
        text = requests.get(url, headers=_headers, timeout=6).text
        _load_page_cache.set(url, text)
    parser = _MinimalHTMLParser()
    parser.feed(text)
    return ' '.join(parser.data)

def search_pages(request):
    res = _search_cache.get(request)
    if res is None:
        print('DDGS', request)
        res = list(DDGS().text(request, max_results=3))
        _search_cache.set(request, res)
    return res

def _split(data, *, model, block_size, overlap=200):
    tokens = model.tokenize(data)
    blocks = []
    i = 0
    while i < len(tokens):
        blocks.append(tokens[i:i + block_size])
        i += block_size - overlap
    return [model.detokenize(b) for b in blocks]

class SearchTask:
    def __init__(self, ctx, ctx_suffix):
        ctx.model = llm.logic_model
        ctx.ask(f'Last message was "{ctx.last_records[-1].content}". Get context from the dialog and write what {ctx.actor.name} will search in internet.')
        self.request = ctx.ask(f'Prepare search request for {ctx.actor.name}. Format as a quoted string', grammar=r'root ::= [A-Za-z0-9А-Яа-я] [^.\n"]* "\""', prefix='"').rstrip('"')[:70]
        #self.request = ctx.ask(f'Prepare search request as a comma-separated list of keywords', grammar=r'root ::= "{" [A-Za-z0-9 ,] [A-Za-z0-9 ,]* "}"')[1:-1].strip()
        #self.request = ctx.ask(f'{ctx.actor.name} searches the answer in internet. Prepare search request. Format as a quoted string', grammar=r'root ::= [A-Za-z0-9] [^.\n"]* "\""', prefix='"').rstrip('"')
        #self.request = ctx.ask(f'Prepare search request using context from the dialog. Format as a quoted string', grammar=r'root ::= [A-Za-z0-9] [^.\n"]* "\""', prefix='"').rstrip('"')[:70]
        self.started = False
        self.page_queue = []
        self.current_page = None
        self.block_queue = []
        self.result = ''
        self.report = ''
        self.ctx = ctx
        self.ctx_suffix = ctx_suffix
        self.max_block_size = max(self.ctx.model.CTX_SIZE - (ctx.token_count + self.ctx.model.token_count(ctx_suffix)) - 1000, 4096)
        self.task_name = f'Web search "{self.request}"'
        self.task_status = f'{self.ctx.actor.name} is searching "{self.request}"'
        self.respond_actions = []
        self.end_handler = None

    def next_action(self):
        if len(self.page_queue) + len(self.block_queue) == 0:
            if self.started:
                return False
            self.started = True
            self.ctx.actor.status = f'{self.ctx.actor.name} is searching "{self.request}"'
            self.page_queue = search_pages(self.request)
            self.report += f'{self.ctx.actor.name} searched "{self.request}"\n'
            if not self.page_queue:
                self.report += 'Nothing found\n'
                return False
            pages = '\n'.join([f'Page {i+1}: {p["body"]}' for i, p in enumerate(self.page_queue)])
            fid = int(self.ctx.ask(f'\n{pages}\nWhich page is the most relevant? Answer 1, 2, or 3.', temperature=0, hidden=True, grammar='root ::= "1" | "2" | "3"')) - 1
            if fid < len(self.page_queue):
                self.page_queue = [self.page_queue[fid]] + self.page_queue[:fid] + self.page_queue[fid + 1:]
            return True
        if not self.block_queue:
            self.current_page = self.page_queue[0]
            self.page_queue = self.page_queue[1:]
            url = self.current_page['href']
            title = self.current_page['title']
            self.report += f'\nURL: {url}\nTITLE: {title}\nSUMMARY:\n'
            self.ctx.actor.append_log(f'Loading: {url}')
            try:
                content = self.current_page['body'] + '\n\n' + load_page_content(url)
            except Exception as e:
                err_str = f'Loading failed.\nURL: {url}\nError: {str(e)}'
                self.ctx.actor.append_log(err_str, prefix = '**  ')
                content = self.current_page['body']
            self.block_queue = _split(content, model=self.ctx.model, block_size=self.max_block_size)
        if self.block_queue:
            self.ctx.actor.status = f'{self.ctx.actor.name} is reading {self.current_page["href"][:70]}'
            self.task_status = self.ctx.actor.status
            self.ctx.push_state()
            page_title = self.current_page['title']
            self.ctx.add(f'\nSEARCH RESULT "{page_title}"\n**********\n{self.block_queue[0]}\n**********\n\n', logging=False)
            self.block_queue = self.block_queue[1:]
            self.report += self.ctx.ask(f'Summarize search result.', temperature=0).strip() + '\n'
            self.ctx.add(f'[Context]\n{self.ctx_suffix}\n[Search request] {self.request}\n\n')
            relevant = 'YES' == self.ctx.ask(f'Does the search result contain a clear answer for the question? (YES/NO)', temperature=0, hidden=True, grammar='root ::= "YES" | "NO"')
            if relevant:
                answer = self.ctx.ask(f'Read search result. Extract all the information related to the question including all details that can be useful.', temperature=0)
                self.result = f'{self.ctx.actor.name} searched "{self.request}"\n' + 'Source: ' + self.current_page['href'] + '\n' + answer
                self.report += f'\nRESULT: {self.result}\n'
                return False
            self.ctx.pop_state()
            return True
        return True
