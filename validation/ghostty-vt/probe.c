/* Synthetic, local C-ABI checks. No PTY, socket, clipboard or process is opened. */
#include <ghostty/vt.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks, failures;
static struct { const char *name; bool supported; char actual[4096]; } observations[2];
static unsigned observation_count;

static void api(GhosttyResult result) {
  if (result != GHOSTTY_SUCCESS) {
    fprintf(stderr, "C API returned %d\n", (int)result);
    exit(2);
  }
}

static void quoted(const char *s) {
  putchar('"');
  for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
    if (*p == '"' || *p == '\\') printf("\\%c", *p);
    else if (*p < 32) printf("\\u%04x", *p);
    else putchar(*p);
  }
  putchar('"');
}

static void check(const char *name, bool passed, const char *actual) {
  if (checks++) putchar(',');
  printf("\n{\"name\":"); quoted(name);
  printf(",\"passed\":%s", passed ? "true" : "false");
  if (actual) { printf(",\"actual\":"); quoted(actual); }
  putchar('}');
  if (!passed) failures++;
}

static void observe(const char *name, bool supported, const char *actual) {
  observations[observation_count].name = name;
  observations[observation_count].supported = supported;
  snprintf(observations[observation_count].actual, sizeof observations[0].actual, "%s", actual);
  observation_count++;
}

static GhosttyTerminal terminal(uint16_t cols, uint16_t rows) {
  GhosttyTerminal t = NULL;
  api(ghostty_terminal_new(NULL, &t, cols, rows));
  return t;
}

static void write_text(GhosttyTerminal t, const char *s) {
  ghostty_terminal_vt_write(t, (const uint8_t *)s, strlen(s));
}

static void text(GhosttyTerminal t, bool unwrap, char *out, size_t capacity) {
  GhosttyFormatter f = NULL;
  api(ghostty_formatter_terminal_new(NULL, &f, t));
  api(ghostty_formatter_set(f, GHOSTTY_FORMATTER_OPT_UNWRAP, &unwrap));
  size_t written = 0;
  api(ghostty_formatter_format_buf(f, (uint8_t *)out, capacity - 1, &written));
  out[written] = 0;
  ghostty_formatter_free(f);
}

static void unicode_checks(void) {
  const char *sample = "a中😀é!";
  const size_t length = strlen(sample);
  char out[4096];
  bool all = true, widths = true;
  for (size_t split = 0; split <= length; split++) {
    GhosttyTerminal t = terminal(80, 24);
    ghostty_terminal_vt_write(t, (const uint8_t *)sample, split);
    ghostty_terminal_vt_write(t, (const uint8_t *)sample + split, length - split);
    text(t, false, out, sizeof out);
    uint16_t x = 0;
    api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_CURSOR_X, &x));
    all = all && strcmp(out, sample) == 0;
    widths = widths && x == 7;
    ghostty_terminal_free(t);
  }
  check("utf8_every_two_chunk_boundary", all, NULL);
  check("cjk_emoji_cell_width_cursor_7", widths, NULL);
  GhosttyTerminal t = terminal(80, 24);
  for (size_t i = 0; i < length; i++) ghostty_terminal_vt_write(t, (const uint8_t *)sample + i, 1);
  text(t, false, out, sizeof out);
  check("utf8_one_byte_chunks", strcmp(out, sample) == 0, out);
  ghostty_terminal_reset(t);
  write_text(t, "e\xcc\x81");
  text(t, false, out, sizeof out);
  uint16_t x = 0;
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_CURSOR_X, &x));
  check("combining_accent_text_and_width", strcmp(out, "e\xcc\x81") == 0 && x == 1, out);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  write_text(t, "\x1b[?2027h👨‍👩‍👧‍👦");
  text(t, false, out, sizeof out);
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_CURSOR_X, &x));
  check("grapheme_mode_2027_zwj_text_and_width", strcmp(out, "👨‍👩‍👧‍👦") == 0 && x == 2, out);
  ghostty_terminal_free(t);
}

static void ansi_checks(void) {
  char out[4096];
  GhosttyTerminal t = terminal(80, 24);
  write_text(t, "\x1b[1;31mR");
  GhosttyStyle style;
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_CURSOR_SGR_STYLE, &style));
  check("sgr_bold_red_style", (style.flags & GHOSTTY_STYLE_FLAG_BOLD) &&
    style.fg_color.tag == GHOSTTY_STYLE_COLOR_PALETTE && style.fg_color.value.palette == 1, NULL);
  write_text(t, "\x1b[0mN");
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_CURSOR_SGR_STYLE, &style));
  text(t, false, out, sizeof out);
  check("sgr_reset_and_text", ghostty_style_is_default(&style) && strcmp(out, "RN") == 0, out);
  ghostty_terminal_reset(t);
  /* The alternate buffer switch does not imply CUP; real redraws issue it. */
  write_text(t, "MAIN\x1b[?1049h\x1b[HALT");
  text(t, false, out, sizeof out);
  check("alternate_screen_enter", strcmp(out, "ALT") == 0, out);
  write_text(t, "\x1b[?1049l");
  text(t, false, out, sizeof out);
  check("alternate_screen_restore", strcmp(out, "MAIN") == 0, out);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  const char *stream = "\x1b[1;31m中\x1b[0m😀";
  for (size_t i = 0; i < strlen(stream); i++) ghostty_terminal_vt_write(t, (const uint8_t *)stream + i, 1);
  text(t, false, out, sizeof out);
  check("ansi_unicode_one_byte_chunks", strcmp(out, "中😀") == 0, out);
  ghostty_terminal_free(t);
  t = terminal(6, 3);
  write_text(t, "abcdefg");
  api(ghostty_terminal_resize(t, 4, 4, 8, 16));
  uint16_t cols = 0, rows = 0;
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_COLS, &cols));
  api(ghostty_terminal_get(t, GHOSTTY_TERMINAL_DATA_ROWS, &rows));
  text(t, true, out, sizeof out);
  check("local_resize_reflow_preserves_text", cols == 4 && rows == 4 && strcmp(out, "abcdefg") == 0, out);
  ghostty_terminal_free(t);
}

static void session_checks(void) {
  const uint8_t half[] = {0xf0, 0x9f};
  const uint8_t tail[] = {0x98, 0x80, 'Z'};
  char out[4096];
  GhosttyTerminal t = terminal(80, 24);
  ghostty_terminal_vt_write(t, half, sizeof half);
  ghostty_terminal_vt_write(t, tail, sizeof tail);
  text(t, false, out, sizeof out);
  check("same_session_partial_utf8_continues", strcmp(out, "😀Z") == 0, out);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  ghostty_terminal_vt_write(t, half, sizeof half);
  ghostty_terminal_reset(t);
  ghostty_terminal_vt_write(t, tail, sizeof tail);
  text(t, false, out, sizeof out);
  observe("reset_isolates_partial_utf8", !strstr(out, "😀") && strstr(out, "Z"), out);
  ghostty_terminal_reset(t);
  write_text(t, "\x1b[31");
  ghostty_terminal_reset(t);
  write_text(t, "mZ");
  text(t, false, out, sizeof out);
  observe("reset_isolates_partial_csi", strcmp(out, "mZ") == 0, out);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  ghostty_terminal_vt_write(t, half, sizeof half);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  ghostty_terminal_vt_write(t, tail, sizeof tail);
  text(t, false, out, sizeof out);
  check("new_instance_isolates_partial_utf8", strcmp(out, "��Z") == 0, out);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  write_text(t, "\x1b[31");
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  write_text(t, "mZ");
  text(t, false, out, sizeof out);
  check("new_instance_isolates_partial_csi", strcmp(out, "mZ") == 0, out);
  ghostty_terminal_free(t);
}

struct Replies { unsigned count; size_t length; uint8_t data[256]; };
static void capture_reply(GhosttyTerminal t, void *userdata, const uint8_t *data, size_t length) {
  (void)t;
  struct Replies *r = userdata;
  r->count++;
  if (length <= sizeof r->data) { memcpy(r->data, data, length); r->length = length; }
  /* Deliberately no transport forwarding: this is a local observation probe. */
}

static void effect_and_key_checks(void) {
  struct Replies replies = {0};
  GhosttyTerminal t = terminal(80, 24);
  api(ghostty_terminal_set(t, GHOSTTY_TERMINAL_OPT_USERDATA, &replies));
  api(ghostty_terminal_set(t, GHOSTTY_TERMINAL_OPT_WRITE_PTY, (const void *)capture_reply));
  write_text(t, "\x1b[6n");
  check("dsr_callback_captured_locally", replies.count == 1 && replies.length == 6 &&
    memcmp(replies.data, "\x1b[1;1R", 6) == 0, NULL);
  api(ghostty_terminal_set(t, GHOSTTY_TERMINAL_OPT_WRITE_PTY, NULL));
  write_text(t, "\x1b[6n\x1b[c");
  check("readonly_policy_drops_replies", replies.count == 1, NULL);
  GhosttyKeyEncoder encoder = NULL;
  GhosttyKeyEvent event = NULL;
  api(ghostty_key_encoder_new(NULL, &encoder));
  api(ghostty_key_event_new(NULL, &event));
  api(ghostty_key_event_set_action(event, GHOSTTY_KEY_ACTION_PRESS));
  api(ghostty_key_event_set_key(event, GHOSTTY_KEY_ARROW_UP));
  uint8_t buf[128]; size_t written = 0;
  api(ghostty_key_encoder_set_from_terminal(encoder, t));
  api(ghostty_key_encoder_encode(encoder, event, buf, sizeof buf, &written));
  check("key_up_normal_mode", written == 3 && memcmp(buf, "\x1b[A", 3) == 0, NULL);
  write_text(t, "\x1b[?1h");
  api(ghostty_key_encoder_set_from_terminal(encoder, t));
  api(ghostty_key_encoder_encode(encoder, event, buf, sizeof buf, &written));
  check("key_up_application_mode", written == 3 && memcmp(buf, "\x1bOA", 3) == 0, NULL);
  ghostty_key_event_free(event);
  ghostty_key_encoder_free(encoder);
  ghostty_terminal_free(t);
  t = terminal(80, 24);
  write_text(t, "\x1b[6n");
  check("callback_not_inherited_by_new_instance", replies.count == 1, NULL);
  ghostty_terminal_free(t);
}

int main(void) {
  printf("{\"libraryVersion\":"); quoted(ghostty_version());
  printf(",\"transportWrites\":0,\"checks\":[");
  unicode_checks(); ansi_checks(); session_checks(); effect_and_key_checks();
  printf("\n],\"observations\":[");
  for (unsigned i = 0; i < observation_count; i++) {
    if (i) putchar(',');
    printf("{\"name\":"); quoted(observations[i].name);
    printf(",\"supported\":%s,\"actual\":", observations[i].supported ? "true" : "false");
    quoted(observations[i].actual); putchar('}');
  }
  printf("],\"checkCount\":%u,\"observationCount\":%u,\"failureCount\":%u}\n", checks, observation_count, failures);
  return failures ? 1 : 0;
}
