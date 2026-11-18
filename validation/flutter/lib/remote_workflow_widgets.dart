import 'package:flutter/material.dart';
import 'design_tokens.dart';

/// Shared presentation for the reviewed herdr connection workflow.
class RemoteWorkflowCard extends StatelessWidget {
  const RemoteWorkflowCard({super.key, required this.tokens, required this.title,
    required this.child, this.subtitle, this.icon = Icons.shield_outlined});
  final DesignTokens tokens;
  final String title;
  final String? subtitle;
  final IconData icon;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 16),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(color: tokens.color('card'),
      border: Border.all(color: tokens.color('border')),
      borderRadius: BorderRadius.circular(18)),
    child: Material(type: MaterialType.transparency, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(padding: const EdgeInsets.all(9),
          decoration: BoxDecoration(color: tokens.color('brandSoft'), borderRadius: BorderRadius.circular(10)),
          child: Icon(icon, size: 20, color: tokens.color('brand'))),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          if (subtitle != null) ...[const SizedBox(height: 4),
            Text(subtitle!, style: TextStyle(fontSize: 12, height: 1.5, color: tokens.color('textSecondary')))],
        ])),
      ]),
      const SizedBox(height: 18), child,
    ])),
  );
}

class RemoteWorkflowSteps extends StatelessWidget {
  const RemoteWorkflowSteps({super.key, required this.tokens, required this.labels, required this.current});
  final DesignTokens tokens;
  final List<String> labels;
  final int current;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 20),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < labels.length; i++) Expanded(child: Column(children: [
        Row(children: [
          Expanded(child: Container(height: 2, color: i == 0 ? Colors.transparent : tokens.color(i <= current ? 'brand' : 'border'))),
          Container(width: 28, height: 28, alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle,
              color: tokens.color(i <= current ? 'brand' : 'cardSubtle')),
            child: i < current ? Icon(Icons.check, size: 16, color: tokens.color('textInverse'))
              : Text('${i + 1}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700,
                  color: tokens.color(i == current ? 'textInverse' : 'textSecondary')))),
          Expanded(child: Container(height: 2, color: i == labels.length - 1 ? Colors.transparent : tokens.color(i < current ? 'brand' : 'border'))),
        ]),
        const SizedBox(height: 8),
        Text(labels[i], textAlign: TextAlign.center,
          style: TextStyle(fontSize: 12, fontWeight: i == current ? FontWeight.w700 : FontWeight.w400,
            color: tokens.color(i == current ? 'brand' : 'textSecondary'))),
      ])),
    ]),
  );
}

class RemoteWorkflowNotice extends StatelessWidget {
  const RemoteWorkflowNotice({super.key, required this.tokens, required this.child, this.warning = false});
  final DesignTokens tokens;
  final Widget child;
  final bool warning;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 16), padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(color: tokens.color(warning ? 'warningSoft' : 'brandSoft'),
      borderRadius: BorderRadius.circular(12)),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(warning ? Icons.info_outline : Icons.verified_user_outlined,
        color: tokens.color(warning ? 'warningText' : 'brand'), size: 18),
      const SizedBox(width: 10), Expanded(child: DefaultTextStyle.merge(
        style: TextStyle(fontSize: 12, height: 1.55, color: tokens.color(warning ? 'warningText' : 'textSecondary')),
        child: child)),
    ]),
  );
}
