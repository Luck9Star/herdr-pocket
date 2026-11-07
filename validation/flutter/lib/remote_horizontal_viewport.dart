import 'package:flutter/material.dart';
import 'package:terminal_view/terminal_view.dart';

/// Local-only remote-grid viewport. Anchors are fractional grid columns so a
/// font or window change does not turn the old pixel offset into a new target.
class RemoteHorizontalViewport extends StatefulWidget {
  const RemoteHorizontalViewport({super.key,required this.identity,required this.anchors,
    required this.style,required this.columns,required this.child});
  final String? identity;
  final Map<String,double> anchors;
  final TerminalStyle style;
  final int columns;
  final Widget child;
  @override
  State<RemoteHorizontalViewport> createState() => _RemoteHorizontalViewportState();
}

class _RemoteHorizontalViewportState extends State<RemoteHorizontalViewport> {
  final scroll = ScrollController(keepScrollOffset:false);
  final sliderPosition = ValueNotifier<({double value,double extent})>((value:0,extent:0));
  double cellWidth = 0, viewportWidth = 0;
  TextStyle? measuredStyle;
  StrutStyle? measuredStrut;
  TextScaler? measuredScaler;
  double measuredWidth = 0;
  int revision = 0;
  bool restoring = false;
  bool sliderSyncPending = false, disposing = false;

  @override
  void initState() { super.initState(); scroll.addListener(save); PaintingBinding.instance.systemFonts.addListener(fontsChanged); }
  void fontsChanged() { measuredStyle = null; if (mounted) setState(() {}); }
  void remember(String? identity,double column) {
    if (identity == null || identity.isEmpty || !column.isFinite) return;
    widget.anchors.remove(identity);
    widget.anchors[identity] = column;
    while (widget.anchors.length > 16) { widget.anchors.remove(widget.anchors.keys.first); }
  }
  void save() {
    if (!restoring && scroll.hasClients && cellWidth > 0) {
      remember(widget.identity,scroll.offset.clamp(scroll.position.minScrollExtent,scroll.position.maxScrollExtent) / cellWidth);
    }
    syncSlider();
  }
  void syncSlider() {
    if (disposing || sliderSyncPending) return;
    sliderSyncPending = true;
    // Scroll metrics can change during layout; update the control only after
    // the frame so its listener never marks widgets dirty while building.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      sliderSyncPending = false;
      if (!mounted || !scroll.hasClients || !scroll.position.hasContentDimensions) return;
      final max = scroll.position.maxScrollExtent;
      sliderPosition.value = (value:max > 0 ? (scroll.offset / max).clamp(0.0,1.0).toDouble() : 0,extent:max);
    });
  }
  @override
  void didUpdateWidget(RemoteHorizontalViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.identity != widget.identity || oldWidget.columns != widget.columns) {
      cellWidth = 0; viewportWidth = 0;
    }
  }
  void restore(double width,double viewport) {
    if (!width.isFinite || width <= 0 || !viewport.isFinite || viewport <= 0) {
      ++revision; restoring = false; cellWidth = 0; viewportWidth = 0; return;
    }
    if (width == cellWidth && viewport == viewportWidth) return;
    cellWidth = width; viewportWidth = viewport;
    final ticket = ++revision, identity = widget.identity;
    restoring = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || ticket != revision || identity != widget.identity) return;
      if (!scroll.hasClients || !scroll.position.hasContentDimensions) {
        restoring = false; cellWidth = 0; viewportWidth = 0; return;
      }
      final position = scroll.position;
      final pixels = (((identity == null || identity.isEmpty ? null : widget.anchors[identity]) ?? 0) * width)
        .clamp(position.minScrollExtent,position.maxScrollExtent).toDouble();
      scroll.jumpTo(pixels);
      remember(identity,pixels / width);
      restoring = false;
      syncSlider();
    });
  }
  @override
  void dispose() { disposing = true; save(); PaintingBinding.instance.systemFonts.removeListener(fontsChanged); scroll.removeListener(save); scroll.dispose(); sliderPosition.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final style = widget.style.toTextStyle(), strut = widget.style.toStrutStyle();
    final scaler = MediaQuery.textScalerOf(context);
    if (style != measuredStyle || strut != measuredStrut || scaler != measuredScaler) {
      final painter = TextPainter(text:TextSpan(text:'mmmmmmmmmm',style:style),strutStyle:strut,
        textDirection:TextDirection.ltr,textScaler:scaler)..layout();
      measuredWidth = painter.width / 10;
      painter.dispose();
      measuredStyle = style; measuredStrut = strut; measuredScaler = scaler;
    }
    final width = measuredWidth;
    return LayoutBuilder(builder:(context,constraints) {
      restore(width,constraints.maxWidth);
      if (!width.isFinite || width <= 0 || !constraints.maxWidth.isFinite || constraints.maxWidth <= 0) return const SizedBox.shrink();
      final overflow = width * widget.columns > constraints.maxWidth;
      final terminalHeight = overflow ? 312.0 : 360.0;
      return Column(children:[
        SizedBox(height:terminalHeight,child:SingleChildScrollView(key:const ValueKey('remote-horizontal-scroll'),
          controller:scroll,scrollDirection:Axis.horizontal,
          child:SizedBox(width:width * widget.columns,height:terminalHeight,child:widget.child))),
        if (overflow)
        SizedBox(key:const ValueKey('remote-horizontal-scrollbar'),height:48,
          child:ValueListenableBuilder<({double value,double extent})>(valueListenable:sliderPosition,builder:(context,position,_) {
            final identity = widget.identity, generation = revision;
            return SliderTheme(data:SliderTheme.of(context).copyWith(
              trackShape:const RectangularSliderTrackShape(),trackHeight:4,
              thumbShape:const RoundSliderThumbShape(enabledThumbRadius:8),
              overlayShape:const RoundSliderOverlayShape(overlayRadius:14)),
              child:Slider(key:const ValueKey('remote-horizontal-slider'),value:position.value,
                semanticFormatterCallback:(v) => '终端横向阅读位置 ${(v * 100).round()}%',
                onChanged:position.extent <= 0 ? null : (v) {
                  if (scroll.hasClients && !restoring && identity == widget.identity && generation == revision) {
                    scroll.jumpTo(v * scroll.position.maxScrollExtent);
                  }
                }));
          })),
      ]);
    });
  }
}
