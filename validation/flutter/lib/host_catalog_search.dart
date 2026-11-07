/// Only public fields explicitly allowed in the local host-list search.
/// No credentials, key handles, fingerprints, paths, draft or terminal output.
class HostSearchFields {
  const HostSearchFields({required this.label,required this.session,required this.host,required this.provider});
  final String label,session,host,provider;
  bool matches(String input) {
    final query=input.trim().toLowerCase();
    if (query.isEmpty) return true;
    final shortProvider=switch(provider) {
      'direct' => 'direct','tailscale' => 'Tailscale','easytier' => 'EasyTier','zerotier' => 'ZeroTier',_ => '',
    };
    return [label,session,host,shortProvider].any((value) => value.toLowerCase().contains(query));
  }
}

enum HostTaskFilter { all,current,history }

/// A declared legacy provider is not the route of a currently bound network.
/// A missing binding record is unknown, never a fallback to the declaration.
String hostSearchProvider(String declared,{required bool hasBinding,String? boundProvider}) =>
  hasBinding ? boundProvider ?? '' : declared;

/// A legacy provider is descriptive data, not an implicit network route.
String hostNetworkDescription({required String declared,required bool requiresBinding,
    required bool hasBinding,String? boundLabel,bool? boundEnabled}) {
  if (requiresBinding) return '待绑定 $declared · 请先在网络管理中配置并选择该网络';
  if (!hasBinding) return declared == 'direct' || declared == 'unspecified'
    ? '系统直连（沿用系统路由）'
    : '系统直连（沿用系统路由） · 旧 provider 标签 $declared 仅为资料';
  if (boundLabel == null || boundEnabled == null) return '网络绑定资料缺失 · 无法确认实际路径，请检查网络配置';
  return '网络绑定：$boundLabel · ${boundEnabled ? '本机启用' : '本机停用'}';
}

/// Preserve the caller's authoritative priority order and original row objects.
List<T> searchHostCatalog<T>(Iterable<T> ordered,{required String query,required HostTaskFilter filter,
  required HostSearchFields Function(T) fields,required bool Function(T) current,required bool Function(T) history}) =>
  ordered.where((host) => fields(host).matches(query) && switch(filter) {
    HostTaskFilter.all => true,HostTaskFilter.current => current(host),HostTaskFilter.history => history(host),
  }).toList();

class HostSearchTarget {
  const HostSearchTarget(this.paneId,this.terminalId,this.state);
  final String paneId,terminalId,state;
}

/// Fresh/current is required independently of a retained blocked count. A
/// duplicate pane or terminal is ambiguous even when its other ID differs.
List<HostSearchTarget> currentSearchTargets(Iterable<HostSearchTarget> values,{required bool fresh,required bool current}) {
  if (!fresh || !current) return const [];
  return _locatableSearchTargets(values);
}
List<HostSearchTarget> historicalSearchTargets(Iterable<HostSearchTarget> values,{required bool fresh,required bool current}) {
  if (fresh && current) return const [];
  return _locatableSearchTargets(values);
}
List<HostSearchTarget> _locatableSearchTargets(Iterable<HostSearchTarget> values) {
  final targets=values.toList(),panes=<String,int>{},terminals=<String,int>{};
  for (final target in targets) {
    panes.update(target.paneId,(count) => count+1,ifAbsent:() => 1);
    terminals.update(target.terminalId,(count) => count+1,ifAbsent:() => 1);
  }
  return targets.where((target) => target.state=='blocked' &&
    RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(target.paneId) &&
    RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(target.terminalId) &&
    panes[target.paneId]==1 && terminals[target.terminalId]==1).toList();
}
