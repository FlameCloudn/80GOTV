# 新版前端接口对照

本表来自当前副本的模板与 JavaScript。静态引用检查不代替真实请求和业务验证。
实际地址数：189；模板固定 endpoint 引用：202；未注册引用：0。

## 浏览器请求

动态拼接的比赛、BP、评论、通知等地址在真实浏览器和针对性接口测试中另行验证。

| 前端位置 | 请求入口 |
| --- | --- |
| `static/js/bracket_editor.js:164` | `fetch('/admin/events/' + window._eventId + '/bracket/api/teams', {` |
| `static/js/bracket_editor.js:812` | `fetch('/admin/events/' + window._eventId + '/bracket/api/save', {` |
| `static/js/front_api.js:29` | `fetchJson(url) {` |
| `static/js/front_api.js:30` | `fetch(url, {` |
| `static/js/front_api.js:95` | `fetchJson('/api/front/home')` |
| `static/js/front_api.js:183` | `fetchJson('/api/front/matches?' + apiParams.toString())` |
| `static/js/guess_player_room.js:106` | `fetch(root.dataset.stateUrl, {` |
| `static/js/guess_player_room.js:137` | `fetch(root.dataset.guessUrl, {` |
| `static/js/main.js:75` | `fetch('/api/front/players?per_page=10', {credentials:'same-origin'}).then(function(r){ return r.json(); }),` |
| `static/js/main.js:76` | `fetch('/api/front/teams', {credentials:'same-origin'}).then(function(r){ return r.json(); }),` |
| `static/js/main.js:77` | `fetch('/api/front/events', {credentials:'same-origin'}).then(function(r){ return r.json(); })` |
| `static/js/main.js:159` | `fetch('/api/search?q=' + encodeURIComponent(q), {` |
| `static/js/main.js:429` | `fetch(form.action, {` |
| `static/js/main.js:545` | `fetch(form.action, {` |
| `static/js/main.js:624` | `fetch('/comment/delete/' + cid, {` |
| `static/js/main.js:654` | `fetch('/comment/like/' + cid, {` |
| `static/js/main.js:673` | `fetch('/notifications/unread-count', {` |
| `static/js/notifications.js:58` | `fetch('/notifications/read/' + id, {` |
| `static/js/notifications.js:126` | `fetch('/notifications/read/' + notification.id, {` |
| `static/js/notifications.js:145` | `fetch('/api/front/notifications', {` |
| `static/js/notifications.js:200` | `fetch('/notifications/read-all', {` |
| `static/js/site_dialogs.js:87` | `fetch(form.action, {` |
| `static/js/stats_side_switch.js:91` | `fetch(url, {` |
| `templates/admin/matches.html:348` | `fetch('/api/bp/' + id + '/undo', {` |
| `templates/admin/news_form.html:159` | `fetch('/admin/upload/image', {` |
| `templates/base.html:359` | `fetch('/api/feedback/submit', {` |
| `templates/bp_room.html:208` | `fetch('/api/bp/' + matchId + '/action', {` |
| `templates/bp_room.html:241` | `fetch('/bp/' + matchId + '/verify', {` |
| `templates/bp_room.html:611` | `fetch('/api/bp/' + matchId + '/state').then(function(r) { return r.json(); }).then(function(data) {` |
| `templates/bp_room.html:622` | `fetch('/api/bp/' + matchId + '/heartbeat', {` |
| `templates/bp_room.html:631` | `fetch('/api/bp/' + matchId + '/reset', {` |
| `templates/login.html:257` | `fetch('/auth/csrf-token', {` |
| `templates/login.html:274` | `fetch(path, {` |
| `templates/login.html:377` | `fetch('/captcha/reload')` |
| `templates/match_data_live.html:613` | `fetch('/api/live/'+MATCH_ID,{cache:'no-store'});` |
| `templates/match_detail.html:743` | `fetch('/matches/{{ match.slug or match.id&#124;tojson }}/vote', {` |
| `templates/match_live.html:253` | `fetch(/api/live/${MATCH_ID}, {cache:'no-store', credentials:'same-origin'});` |
| `templates/notifications.html:34` | `fetch('/notifications/read/' + notifId, {` |
| `templates/notifications.html:49` | `fetch('/notifications/read-all', {` |

## 模板引用缺口

没有发现固定 `url_for` 指向未注册地址。
