# 微信 Computer-Use Verification

Date: 2026-09-21. Live window `com.tencent.xinWeChat`, 1213x884, warm driver
daemon. All readings are from the AX tree; no OCR.

## Summary

| # | Target | Result | Evidence |
| --- | --- | --- | --- |
| 1 | 会话列表 | PASS | `AXList` `identifier=session_list`, 12 items each with own identifier |
| 2 | 聊天内容显示框 | PASS | `AXList` `identifier=chat_message_list`, bubbles carried in `title` |
| 3 | 输入框 | PASS | `AXTextArea` `identifier=chat_input_field`, `settable=true`, round-trip proven |
| 4 | 通讯录 | PASS | nav button `label=通讯录`, postcondition `AXList title=通讯录` |
| 5 | 发送者 + 内容 | **PARTIAL** | content fully parseable; sender is **not** exposed |
| 6 | 会话切换与选中态 | PASS (switch) / vision-only (highlight) | header `current_chat_name_label` tracks the open chat; row highlight is pixels only |

## 1. 会话列表 — PASS

```text
AXList  chain=0.10.1.0.7  identifier=session_list  title=会话  200x772@(2447,474)
```

12 children, one per conversation. Unlike the message list, each item has a
**unique, meaningful identifier** that includes the conversation name:

```text
session_item_文件助手        session_item_李嘉龙、Joy    session_item_全家总动员
session_item_张家小不点们     session_item_姐姐           session_item_-粒粒
session_item_李嘉龙          session_item_付邦           session_item_张书玮
session_item_Kinson         session_item_尹惠霖         session_item_亮
```

Each item's value is a newline-delimited record:

```text
付邦\n已置顶\n4b,8b的估计还好\n00:42\n
```

Fields present: conversation name, pin marker, last message preview, time.
The preview even preserves the sender prefix when a group message is shown
(`姐姐: 这个很好吃…`, `Joy: [动画表情] 自信`).

Withdrawal notice: identifiers embed the conversation name, so a rename
changes the identifier. Treat it as a strong anchor, not a permanent key; keep
the label and the chain as fallbacks.

## 2. 聊天内容显示框 — PASS (with a caveat)

```text
AXList  chain=0.10.1.0.4.9  identifier=chat_message_list  title=消息  950x509@(2648,475)
```

Message bubbles appear as direct children:

```text
chain=0.10.1.0.4.9.30  role=AXStaticText  identifier=chat_bubble_item_view  950x200@(2648,307)  title='图片'
chain=0.10.1.0.4.9.31  role=AXStaticText  identifier=chat_bubble_item_view  950x57@(2648,507)   title='回来取一下哈'
```

**Message text is in `title`, not `value`.** `value` is empty on every bubble.
A reader that only checks `value` will see nothing.

Caveat — the list is a **virtual scroller**. In a long conversation the tree
contained 50 placeholder `AXStaticText` nodes with `identifier=virtual_cell`,
geometry `0x0@(0,0)`, and no text, against only 6-7 real bubbles. Placeholders
are inert but they dominate node count, so any container member filter must
exclude zero-geometry nodes.

Also, only the loaded window of history is present. Reading a full conversation
requires scrolling, and the bubble set is not stable across observations.

## 3. 输入框 — PASS

```text
AXTextArea  chain=0.10.1.0.4.8  identifier=chat_input_field  settable=true
```

Verified round trip:

```text
guard set_value : allow structured_prior_match
act             : set_value performed
value after     : 'macjev-probe'   -> postcondition value_equals: True
cleared back    : ''
```

The input box is addressable and writable without any coordinate click.

Note: there is a second `AXTextArea` at `0.10.1.0.7` with no identifier — that
is the conversation search box, not the composer. Match on the identifier.

## 4. 通讯录 — PASS

Navigation container: anonymous `AXGroup` at `chain=0` with 11 children, of
which 10 are labelled buttons (`微信`, `通讯录`, `收藏`, `朋友圈`, `视频号`,
`搜一搜`, `游戏中心`, `小程序面板`, `手机`, `更多`).

Clicking `通讯录` changes the tree from 132 to 58 elements and produces:

```text
AXList  title=通讯录
AXStaticText  value=A00🐬和平鑫城手机店~古丽美
AXStaticText  value=AAAerji
AXStaticText  value=AAA曹宇
```

Contact names are readable, so contact lookup does not need OCR.

Important: these nav buttons expose **no `AXPress`**. They are clickable only
through a guarded point click. Element press returns
`element_action_unavailable`.

### Postcondition choice

`window_title_changed` does **not** work: 微信's window title stays `微信`
across tabs. Use `tree_contains` (`AXList` titled `通讯录`) or an element-count
delta (132 -> 58).

## 5. 发送者 + 内容 — PARTIAL

Content parses. Sender does not.

Full attribute set on a real bubble:

```json
{
  "role": "AXStaticText",
  "identifier": "chat_bubble_item_view",
  "title": "4b,8b的估计还好",
  "value": "",
  "description": "",
  "subrole": null,
  "position": {"x": 2648, "y": 915},
  "size": {"width": 950, "height": 57},
  "actions": []
}
```

Measured across three conversations (付邦, 姐姐, 文件助手):

- every bubble has `identifier=chat_bubble_item_view` — identical, no sender;
- every bubble has `x=2648` and `width=950` — the full pane, so left/right
  alignment is not exposed;
- `role`, `description`, `subrole` are identical for all bubbles;
- no sibling node carries a sender name; only a time divider appears
  (`星期三 05:48`), and it is not attached to a specific bubble.

So the AX tree gives **text order only**. Who said what cannot be derived from
structure. Distinguishing "me" from "them" requires either the visible avatar
(vision) or an app-side data source.

What is still reliable without OCR: the sequence of message texts, message
count, image/voice/call placeholders (`图片`, `[动画表情]`, `语音通话`), and
the time divider.

## 6. 会话切换与选中态

Verified against three real conversations (付邦 / 姐姐 / 全家总动员) after the
user pointed out that the highlighted row colour differs, the composer looks
identical, and the message content differs. All three observations were
checked.

**Row highlight is pure pixels.** `session_list` and all 12 `session_item_*`
children expose only `AXEnabled=1`. There is no `AXSelected`, no `AXFocused`,
no value-prefix marker, and `AXSelectedTextRange` is `0,0` on every row. A
native dump of every attribute name (`AXUIElementCopyAttributeNames`) on the
list and its rows finds no selection attribute at all. Pixel sampling of the
list column:

| Row | Sample px | RGB |
| --- | --- | --- |
| 付邦 (current) | (220,166) | (68,68,68) |
| 姐姐 | (220,98) | (47,47,47) |
| 文件助手 | (220,234) | (47,47,47) |
| 张家小不点们 | (220,302) | (47,47,47) |

So "which row is selected" cannot be read structurally. It is a
vision-required fact.

**The open conversation is structured anyway.** The chat header exposes:

```text
current_chat_name_label   AXStaticText  value='全家总动员'   (group)
current_chat_count_label  AXStaticText  value='(7)'          (group only)
big_title_line_h_view     AXStaticText  value='全家总动员(7)'
```

After switching to 付邦 (1:1), `current_chat_count_label` disappears and
`current_chat_name_label.value` becomes `付邦`. This is a better switch
postcondition than the window title (permanently `微信`) or tree size, and it
needs no screenshot. Group vs 1:1 changes the header child set, so a missing
`current_chat_count_label` is a 1:1 signal, not an error.

**The composer is one control across conversations.** `chat_input_field` keeps
role, identifier and geometry `926x245@(2664,1033)`; only `title` changes with
the conversation name. Its `element_id` changes across a switch (the name is
part of the identity hash) while `session_list` and
`current_chat_name_label` keep a stable `element_id`.

**Guard already fails safe here.** `guard` against an older revision with an
`element_id` from that revision returns `deny / candidate_not_found`
("element_id is not in the bound observation"). `act` on a session row returns
`element_action_unavailable` ("does not expose AXPress") instead of clicking
something arbitrary, so coordinate click stays the normal path for rows.

**Activation bug reproduced a second time.** A coordinate click at
`(2547,576)`, confirmed by `hit-test` to be exactly `session_item_付邦`
(chain `0.10.1.0.8.1`), silently did nothing on the first attempt and switched
correctly on the retry that ran with the app already frontmost. `performed`
was `true` in both cases, so replay must assert app-active state or a
postcondition, never the click result.

## Implications

1. A 微信 flow can read conversations, pick a conversation, read a message
   window, and send text — all structurally.
2. Any flow step that needs "which side sent this" cannot be structural. That
   step must be marked as vision-required, and its postcondition cannot be a
   sender assertion.
3. Container member filters must drop zero-geometry nodes, or the virtual
   scroller placeholders will be counted as members.
4. 微信 nav buttons need the guarded point-click path; element press is not
   available.

## Reproduction

```bash
export MACJEV_HOME=/tmp/wx-home
PYTHONPATH=src python3 -m macjev.cli computer daemon-start
```

Then observe window `296` and inspect `session_list` / `chat_message_list`.
