function show_hidden(show) {
    if (show)
        document.getElementById('chat').classList.remove('no_hidden');
    else
        document.getElementById('chat').classList.add('no_hidden');
    window.scrollTo(0, document.body.scrollHeight);
}

var chat_id = '';
var user_name;
var char_name;
var next_id = 0;
var chat_template = '';
var chat_args = {};

var userkey = '';
var templates = {};
var chats = {};

function record_view(rec) {
    let div = document.createElement("div");
    div.setAttribute('time', rec.time);
    div.className = 'chat_msg';
    content = rec.content;
    if (rec.role == user_name)
        div.classList.add("record_user");
    else if (rec.role[0] == '[') {
        div.classList.add("record_hidden");
        content = rec.role + '\n' + content;
    } else {
        div.classList.add("record_response");
        content = content.replace(`${char_name}: `, '');
        content = content.replace(`${char_name}:`, '');
    }
    content = content.replace('<', '&lt;').replace('>', '&gt;');
    let formatted = '';
    let last = 0;
    while (last < content.length) {
        let pos = last;
        while (pos < content.length && content[pos] != '`' && content[pos] != '*' && content[pos] != '"') pos++;
        if (pos != last) formatted += content.substring(last, pos);
        last = pos;
        if (pos == content.length) break;
        if (content[pos] == '`' && content.indexOf('```', pos) == pos) {
            pos = content.indexOf('\n', pos);
            if (pos == -1) break;
            let end = content.indexOf('```', pos);
            if (end == -1) end = last;
            let sub = content.substring(pos + 1, end);
            formatted += `<pre>${sub}</pre>`;
            last = end + 3;
            if (last < content.length && content[last] == '\n') last++;
            continue;
        }
        pos++;
        while (pos < content.length && content[pos] != content[last] && content[pos] != '\n') pos++;
        if (content[pos] != content[last]) {
            formatted += content.substring(last, pos);
            last = pos;
            continue;
        }
        let sub = content.substring(last, pos + 1);
        if (content[last] == '`') {
            formatted += `<span class="raw">${sub.substring(1, sub.length - 1)}</span>`;
        } else if (content[last] == '*') {
            formatted += `<span class="asterisk">${sub}</span>`;
        } if (content[last] == '"') {
            formatted += `<span class="quoted">${sub}</span>`;
        }
        last = pos + 1;
    }
    content = formatted.replaceAll(/(https?:\/\/[^ \)\]\n,;]*)/g, '<a href="$1" target="_blank">$1</a>');
    div.innerHTML = content.replaceAll('\n', '<br/>');
    let time_str = document.createElement("span");
    time_str.className = 'msg_time';
    time_str.innerText = new Date(rec.time * 1000).toLocaleTimeString('en-GB');
    div.appendChild(time_str);
    return div;
}

var check_needed = true;
var typing_dots = '';

async function check_messages() {
    if (!check_needed || chat_id == '') return;
    let response = await fetch("/get_chat", {
        method: "POST",
        body: JSON.stringify({
            userkey: userkey,
            chatid: chat_id,
            from: next_id,
        }),
        headers: {"Content-type": "application/json; charset=UTF-8"}
    });
    let res = await response.json();
    user_name = res.user;
    char_name = res.char;
    chat_template = res.template;
    chat_args = res.template_args;
    document.getElementById('user_name').innerText = user_name;
    document.getElementById('char_name').innerText = char_name;
    let chat = document.getElementById('chat');
    for (let r of res.records) {
        if (chat.lastChild == null || r.time - chat.lastChild.getAttribute('time') > 3600 * 4) {
            let time_str = document.createElement("div");
            time_str.className = 'msg_time';
            time_str.innerText = new Date(r.time * 1000).toLocaleString('en-GB');
            chat.appendChild(time_str);
        }
        next_id = r.id + 1;
        chat.appendChild(record_view(r));
    }
    let drafts = document.getElementById('chat_draft');
    drafts.innerHTML = '';
    for (let r of res.draft_records) {
        drafts.appendChild(record_view(r));
    }
    check_needed = res.status != '' || res.draft_records.length > 0;
    if (check_needed) {
        if (typing_dots.length >= 3)
            typing_dots = '';
        else
            typing_dots = typing_dots + '.';
        document.getElementById('status').innerText = res.status + typing_dots;
    } else {
        document.getElementById('status').innerText = ' ';
    }
    if (res.records.length > 0) {
        window.scrollTo(0, document.body.scrollHeight);
    }
}

async function init() {
    document.getElementById('add_message_content').value = '';
    document.getElementById('show_hidden').onclick();
    userkey = localStorage.getItem('userkey');
    await update_user();
    setInterval(check_messages, 500);
}

async function update_user() {
    let public_access = await (await fetch("/check_public_access")).json();
    var res;
    while (true) {
        if (userkey == '') {
            if (public_access.allowed) {
                userkey = prompt(`Enter user key if you already have one, or press Cancel to use new key "${public_access.suggested_key}"`);
                if (userkey == null) userkey = public_access.suggested_key;
            } else {
                userkey = prompt('Enter user key');
            }
        }
        if (userkey == null) userkey = '';
        localStorage.setItem('userkey', userkey);
        if (userkey != '') {
            let response = await fetch("/user", {
                method: "POST",
                body: JSON.stringify({userkey: userkey}),
                headers: {"Content-type": "application/json; charset=UTF-8"}
            });
            res = await response.json();
            if (res.ok == true) break;
        }
        userkey = '';
    }
    templates = res.templates;
    chats = res.chats;
    let sel = document.getElementById('select_template');
    sel.options.length = 0;
    for (const key in res.templates) {
        let spec = res.templates[key];
        var option = document.createElement("option");
        option.value = key;
        option.text = spec.name;
        sel.add(option);
    }
    selected_template_changed();
    let selc = document.getElementById('select_chat');
    selc.options.length = 1;
    let last_chatid = localStorage.getItem('chatid');
    for (const cid in res.chats) {
        var option = document.createElement("option");
        option.value = cid;
        option.text = res.chats[cid];
        selc.add(option);
        if (cid == last_chatid && last_chatid != '') selc.value = last_chatid;
    }
    selected_chat_changed(selc.value);
}

function selected_template_changed() {
    let key = document.getElementById('select_template').value;
    let spec = templates[key];
    let tdata = document.getElementById('template_data');
    tdata.innerHTML = `<div><span class="var_label">Scenario</span> ${spec.scenario}</div>`;
    for (const arg_key in spec.args) {
        let arg = spec.args[arg_key];
        let d = document.createElement("div");
        let elid = 'arg_' + arg_key;
        let labelHTML = `<label for="${elid}" class="var_label">${arg.description}</label> `;
        if (Array.isArray(arg.type)) {
            let sel = document.createElement("select");
            sel.id = elid;
            for (let opt of arg.type) {
                var option = document.createElement("option");
                option.value = opt;
                option.text = opt;
                sel.add(option);
            }
            sel.value = arg.default;
            d.innerHTML = labelHTML;
            d.appendChild(sel);
        } else if (arg.type == 'checkbox') {
            d.innerHTML = labelHTML + `<input type='checkbox' id="${elid}" />`;
            d.lastChild.checked = arg.default;
        } else if (arg.type == 'text') {
            d.innerHTML = labelHTML + `<input type='text' id="${elid}" style="width: 300px" />`;
            d.lastChild.value = arg.default;
        } else if (arg.type == 'textarea') {
            d.innerHTML = labelHTML + `<textarea id="${elid}">${arg.default}</textarea>`;
        } else {
            alert('Unknown arg type: ' + arg.type);
        }
        tdata.appendChild(d);
    }
}

function new_chat_like_this() {
    document.getElementById('select_template').value = chat_template;
    selected_template_changed();
    document.getElementById('select_chat').value = 'new';
    for (arg in chat_args) {
        let el = document.getElementById('arg_' + arg);
        if (el == null) continue;
        let value = chat_args[arg];
        if (typeof value == 'boolean')
            el.checked = value;
        else
            el.value = value;
    }
    show_new();
}

function show_user_key() {
    alert(`Your user key: ${userkey}`);
}

async function set_user() {
    if (!confirm(`Logout?\nSave user key to be able to open your chats later:\n${userkey}`))
        return;
    userkey = '';
    chat_id = '';
    next_id = 0;
    localStorage.setItem('userkey', '');
    await update_user();
}

var settings_shown = false;

function show_main() {
    settings_shown = false;
    document.getElementById('chat_main').style = '';
    document.getElementById('chat_new').style = 'display: none';
    document.getElementById('chat_settings').style = 'display: none';
    document.getElementById('char_name').style = '';
    document.getElementById('user_name').style = '';
}

function show_new() {
    document.getElementById('chat_main').style = 'display: none';
    document.getElementById('chat_new').style = '';
    document.getElementById('chat_settings').style = 'display: none';
    document.getElementById('char_name').style = 'visibility: hidden';
    document.getElementById('user_name').style = 'visibility: hidden';
}

function toggle_settings() {
    if (settings_shown) {
        show_main();
    } else {
        settings_shown = true;
        document.getElementById('chat_main').style = '';
        document.getElementById('chat_new').style = 'display: none';
        document.getElementById('chat_settings').style = '';
    }
}

async function new_chat() {
    let template_key = document.getElementById('select_template').value;
    let args = {};
    let args_spec = templates[template_key].args;
    for (const arg in args_spec) {
        let t = args_spec[arg].type;
        if (t == 'checkbox')
            args[arg] = document.getElementById('arg_' + arg).checked;
        else
            args[arg] = document.getElementById('arg_' + arg).value;
    }
    let response = await fetch("/new_chat", {
        method: "POST",
        body: JSON.stringify({
            userkey: userkey,
            template: template_key,
            args: args,
        }),
        headers: {"Content-type": "application/json; charset=UTF-8"}
    });
    if (response.status != 200) {
        alert('Error ' + response.status);
        return;
    }
    let res = await response.json();
    chat_id = res.new_chat;
    chats[chat_id] = true;
    sel = document.getElementById('select_chat');
    var option = document.createElement("option");
    option.value = chat_id;
    option.text = res.chat_title;
    sel.add(option);
    document.getElementById('select_chat').value = chat_id;
    selected_chat_changed(chat_id);
}

function selected_chat_changed(id) {
    if (id == 'new') {
        show_new();
        return;
    }
    localStorage.setItem('chatid', id);
    chat_id = id;
    next_id = 0;
    document.getElementById('chat').innerHTML = '';
    show_main();
    check_needed = true;
    check_messages();
}

async function add_message_keypress(e) {
    if (e.keyCode == 13 && !e.shiftKey) {
        e.preventDefault();
        let msg_content = document.getElementById('add_message_content');
        let content = msg_content.value.trim()
        let response = await fetch("/add", {
            method: "POST",
            body: JSON.stringify({
                userkey: userkey,
                chatid: chat_id,
                role: user_name,
                tz_offset: new Date().getTimezoneOffset() * -60,
                content: content}),
            headers: {"Content-type": "application/json; charset=UTF-8"}
        });
        if (response.status != 200) {
            alert('Error ' + response.status);
            return;
        }
        msg_content.value = '';
        check_needed = true;
    } else {
        window.scrollTo(0, document.body.scrollHeight);
    }
}

async function remove_chat() {
    if (chat_id == '' || !confirm("Remove this chat?")) return;
    let id = chat_id;
    chat_id = '';
    check_needed = false;
    let response = await fetch("/delete_chat", {
        method: "POST",
        body: JSON.stringify({
            userkey: userkey,
            chatid: id}),
        headers: {"Content-type": "application/json; charset=UTF-8"}
    });
    if (response.status != 200) {
        alert('Error ' + response.status);
        return;
    }
    delete chats[id];
    var sel = document.getElementById("select_chat");
    for (var i = 0; i < sel.length; i++) {
        if (sel.options[i].value == id)
            sel.remove(i);
    }
    show_new();
}

async function remove_last() {
    if (next_id == 0) return;
    let response = await fetch("/remove_last", {
        method: "POST",
        body: JSON.stringify({
            userkey: userkey,
            chatid: chat_id,
            new_end: next_id - 1}),
        headers: {"Content-type": "application/json; charset=UTF-8"}
    });
    if (response.status != 200) {
        alert('Error ' + response.status);
        return;
    }
    next_id -= 1;
    let chat = document.getElementById('chat');
    chat.removeChild(chat.lastChild);
    while (chat.lastChild.className == 'msg_time') {
        chat.removeChild(chat.lastChild);
    }
}
