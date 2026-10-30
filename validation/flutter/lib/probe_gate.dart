import 'dart:collection';
import 'dart:convert';

enum InputMode { observe, direct, draft }

class Ticket {
  const Ticket(this.target, this.generation, this.epoch, this.focus);
  final String target;
  final int generation, epoch, focus;
}

class Frame {
  const Frame(this.ticket, this.data, {this.full = false});
  final Ticket ticket;
  final String data;
  final bool full;
  int get bytes => utf8.encode(data).length;
}

/// Local fixture boundary. This is not a transport or an SSH trust decision.
class ProbeGate {
  ProbeGate(this.target, {this.maxQueuedBytes = 65536});
  final String target;
  final int maxQueuedBytes;
  final Queue<Frame> _queue = Queue<Frame>();
  int generation = 1, epoch = 1, focus = 0;
  int queuedBytes = 0, peakQueuedBytes = 0, receivedBytes = 0;
  int rejectedInputs = 0, rejectedFrames = 0, inputCount = 0;
  bool connected = true, fresh = false, visible = true, active = false;
  bool unknownResult = false;
  InputMode mode = InputMode.observe;
  final List<String> inputHex = [];
  final List<String> unknownHex = [];
  String lastResult = '观察 fixture；没有真实 SSH 连接';

  Ticket get ticket => Ticket(target, generation, epoch, focus);
  bool sameStream(Ticket t) => t.target == target &&
      t.generation == generation && t.epoch == epoch;
  bool current(Ticket t) => sameStream(t) && t.focus == focus;
  bool get canInput => connected && fresh && visible && active && !unknownResult;

  void select(bool value) {
    if (active != value) { focus++; mode = InputMode.observe; }
    active = value;
  }

  void setMode(InputMode value) { focus++; mode = value; }

  void invalidate({bool disconnect = false}) {
    generation += disconnect ? 1 : 0;
    epoch++;
    focus++;
    mode = InputMode.observe;
    fresh = false;
    if (disconnect) connected = false;
    _queue.clear();
    queuedBytes = 0;
  }

  void hide() { visible = false; invalidate(); }
  void resume() { visible = true; connected = true; invalidate(); }

  bool enqueue(Frame frame) {
    if (!sameStream(frame.ticket) || !connected || !visible ||
        (!fresh && !frame.full && !_queue.any((f) => f.full))) {
      rejectedFrames++;
      return false;
    }
    if (queuedBytes + frame.bytes > maxQueuedBytes) {
      rejectedFrames++;
      invalidate();
      lastResult = '输出超过预算；已停止，需显式获取新 full';
      return false;
    }
    _queue.add(frame);
    queuedBytes += frame.bytes;
    if (queuedBytes > peakQueuedBytes) peakQueuedBytes = queuedBytes;
    return true;
  }

  Frame? consume() {
    if (_queue.isEmpty) return null;
    final frame = _queue.removeFirst();
    queuedBytes -= frame.bytes;
    if (!sameStream(frame.ticket)) { rejectedFrames++; return null; }
    if (frame.full) fresh = true;
    receivedBytes += frame.bytes;
    return frame;
  }

  bool send(Ticket captured, String text, InputMode source) {
    if (!current(captured) || !canInput || mode != source ||
        source == InputMode.observe || text.isEmpty || utf8.encode(text).length > 4096) {
      rejectedInputs++;
      return false;
    }
    final hex = utf8.encode(text).map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    inputHex.add(hex);
    if (inputHex.length > 16) inputHex.removeAt(0);
    inputCount++;
    lastResult = '本地 fixture sink 已接收；不是远端执行结果';
    return true;
  }

  void markUnknown() {
    if (inputHex.isNotEmpty) {
      unknownHex.add(inputHex.last);
      if (unknownHex.length > 8) unknownHex.removeAt(0);
    }
    unknownResult = true;
    invalidate(disconnect: true);
    lastResult = '发送结果未知；不会重放，先恢复 full 再人工核实';
  }

  void acknowledgeUnknown() {
    if (connected && fresh) {
      unknownResult = false;
      lastResult = '已人工核实示例状态；旧输入未重放';
    }
  }
}
