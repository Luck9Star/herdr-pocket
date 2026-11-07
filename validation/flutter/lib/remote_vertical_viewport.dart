import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:terminal_view/terminal_view.dart';

void rememberRemoteVerticalAnchor(Map<String,double> anchors,String? identity,double row) {
  if (identity == null || identity.isEmpty || !row.isFinite || row < 0) return;
  anchors.remove(identity); anchors[identity] = row;
  while (anchors.length > 16) { anchors.remove(anchors.keys.first); }
}

double? restoredRemoteVerticalOffset(Map<String,double> anchors,String? identity,double lineHeight,double min,double max) {
  final row = identity == null || identity.isEmpty ? null : anchors[identity];
  if (row == null || !row.isFinite || row < 0 || !lineHeight.isFinite || lineHeight <= 0 ||
      !min.isFinite || !max.isFinite || max < min) return null;
  return (row * lineHeight).clamp(min,max).toDouble();
}

/// Explicit local reading control also works when the TUI owns wheel/touch
/// gestures (alternate buffer or mouse reporting). It never emits terminal input.
class RemoteVerticalViewport extends StatefulWidget {
  const RemoteVerticalViewport({super.key,required this.identity,required this.anchors,
    required this.frame,required this.fresh,required this.builder});
  final String? identity;
  final Map<String,double> anchors;
  // The terminal instance changes only after an accepted full frame.
  final Object frame;
  final bool fresh;
  final Widget Function(ScrollController controller) builder;
  @override
  State<RemoteVerticalViewport> createState() => _RemoteVerticalViewportState();
}

class _RemoteVerticalViewportState extends State<RemoteVerticalViewport> {
  ScrollController scroll = ScrollController(keepScrollOffset:false);
  final position = ValueNotifier<({double value,double extent})>((value:0,extent:0));
  final viewportKey = GlobalKey();
  Object? measuredFrame;
  String? measuredIdentity;
  double lineHeight = 0,viewportHeight = 0,extent = 0;
  bool pending = false,wasFresh = false,userScrolling = false,restoring = false;
  @override
  void initState() { super.initState(); scroll.addListener(sync); }
  @override
  void didUpdateWidget(RemoteVerticalViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.identity != widget.identity) {
      // A fresh controller lets the renderer choose its normal initial view;
      // another target's pixel offset must never become this target's anchor.
      final old = scroll; old.removeListener(sync);
      scroll = ScrollController(keepScrollOffset:false)..addListener(sync);
      WidgetsBinding.instance.addPostFrameCallback((_) => old.dispose());
      measuredFrame = null; measuredIdentity = null; lineHeight = 0; userScrolling = false;
    }
  }
  double? renderedLineHeight() {
    RenderTerminal? terminal;
    void find(RenderObject object) {
      if (object is RenderTerminal) { terminal = object; return; }
      object.visitChildren(find);
    }
    final render = viewportKey.currentContext?.findRenderObject();
    if (render != null) find(render);
    return terminal?.lineHeight;
  }
  void remember() {
    if (restoring || !scroll.hasClients || lineHeight <= 0 || !identical(measuredFrame,widget.frame) || measuredIdentity != widget.identity) return;
    final metrics = scroll.position;
    rememberRemoteVerticalAnchor(widget.anchors,widget.identity,
      scroll.offset.clamp(metrics.minScrollExtent,metrics.maxScrollExtent) / lineHeight);
  }
  void sync() {
    if (pending) return;
    pending = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      pending = false;
      if (!mounted || !scroll.hasClients || !scroll.position.hasContentDimensions) return;
      final height = renderedLineHeight(),metrics = scroll.position;
      final max = metrics.maxScrollExtent;
      if (height != null && height.isFinite && height > 0) {
        final changed = !identical(measuredFrame,widget.frame) || measuredIdentity != widget.identity ||
          height != lineHeight || metrics.viewportDimension != viewportHeight || max != extent || (!wasFresh && widget.fresh);
        measuredFrame = widget.frame; measuredIdentity = widget.identity;
        lineHeight = height; viewportHeight = metrics.viewportDimension; extent = max; wasFresh = widget.fresh;
        final offset = widget.fresh && changed ? restoredRemoteVerticalOffset(widget.anchors,widget.identity,
          height,metrics.minScrollExtent,max) : null;
        // Missing anchors leave terminal_view's normal initial/sticky-bottom
        // behavior alone. Only an accepted fresh full can restore saved rows.
        if (offset != null) {
          restoring = true;
          try { scroll.jumpTo(offset); } finally { restoring = false; }
        }
      }
      position.value = (value:max > 0 ? (scroll.offset / max).clamp(0.0,1.0).toDouble() : 0,extent:max);
    });
  }
  @override
  void dispose() { scroll.removeListener(sync); scroll.dispose(); position.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    sync();
    return Column(children:[
      NotificationListener<ScrollMetricsNotification>(onNotification:(notification) { sync(); return false; },
        child:NotificationListener<ScrollNotification>(onNotification:(notification) {
          if (notification.metrics.axis == Axis.vertical) {
            if (notification is UserScrollNotification) userScrolling = notification.direction != ScrollDirection.idle;
            if (notification is ScrollUpdateNotification && (notification.dragDetails != null || userScrolling)) remember();
            if (notification is ScrollEndNotification) { if (userScrolling) remember(); userScrolling = false; }
          }
          return false;
        },child:KeyedSubtree(key:viewportKey,child:widget.builder(scroll)))),
      SizedBox(height:48,child:Row(children:[
        const Icon(Icons.swap_vert,size:20,semanticLabel:'终端纵向阅读'),
        Expanded(child:ValueListenableBuilder<({double value,double extent})>(valueListenable:position,
          builder:(context,current,_) {
            final identity = widget.identity,frame = widget.frame;
            return Slider(key:const ValueKey('remote-vertical-slider'),value:current.value,
            semanticFormatterCallback:(value) => '终端纵向阅读位置 ${(value * 100).round()}%',
            onChanged:current.extent <= 0 ? null : (value) {
              if (scroll.hasClients && identity == widget.identity && identical(frame,widget.frame)) {
                scroll.jumpTo(value * scroll.position.maxScrollExtent); remember();
              }
            });
          })),
      ])),
    ]);
  }
}
