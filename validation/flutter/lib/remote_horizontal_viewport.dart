import 'package:flutter/material.dart';
import 'package:terminal_view/terminal_view.dart';

/// Local-only 80-column viewport. Anchors are fractional grid columns so a
/// font or window change does not turn the old pixel offset into a new target.
class RemoteHorizontalViewport extends StatefulWidget {
  const RemoteHorizontalViewport({super.key,required this.identity,required this.anchors,
    required this.style,required this.child});
  final String? identity;
  final Map<String,double> anchors;
  final TerminalStyle style;
  final Widget child;
  @override
  State<RemoteHorizontalViewport> createState() => _RemoteHorizontalViewportState();
}

class _RemoteHorizontalViewportState extends State<RemoteHorizontalViewport> {
  final scroll = ScrollController(keepScrollOffset:false);
  double cellWidth = 0, viewportWidth = 0;
  TextStyle? measuredStyle;
  StrutStyle? measuredStrut;
  TextScaler? measuredScaler;
  double measuredWidth = 0;
  int revision = 0;
  bool restoring = false;

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
  }
  @override
  void didUpdateWidget(RemoteHorizontalViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.identity != widget.identity) { cellWidth = 0; viewportWidth = 0; }
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
    });
  }
  @override
  void dispose() { save(); PaintingBinding.instance.systemFonts.removeListener(fontsChanged); scroll.removeListener(save); scroll.dispose(); super.dispose(); }

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
      return Scrollbar(key:const ValueKey('remote-horizontal-scrollbar'),controller:scroll,
        thumbVisibility:true,trackVisibility:true,interactive:true,thickness:12,
        child:SingleChildScrollView(key:const ValueKey('remote-horizontal-scroll'),
        controller:scroll,scrollDirection:Axis.horizontal,
        child:SizedBox(width:width * 80,height:360,child:widget.child)));
    });
  }
}
