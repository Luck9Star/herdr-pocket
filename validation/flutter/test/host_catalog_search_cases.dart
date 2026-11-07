import '../lib/host_catalog_search.dart';

void _check(bool value,String message) { if (!value) throw StateError(message); }
String _ids(List<Map<String,String>> rows) => rows.map((row) => row['id']).join(',');

/// Shared assertions run by the Flutter test runner and the SDK-only probe.
void hostCatalogSearchCases(void Function(String,void Function()) test) {
  final entries=<Map<String,String>>[
    {'id':'a','label':'Same Machine','session':'Build Work','host':'100.64.0.1','provider':'tailscale','private':'opaque-secret'},
    {'id':'b','label':'Same Machine','session':'Dev Work','host':'dev.example.test','provider':'direct','private':'never-search'},
    {'id':'c','label':'中文主机','session':'deploy','host':'10.4.0.3','provider':'easytier'},
    {'id':'d','label':'Other','session':'review','host':'10.4.0.4','provider':'zerotier'},
    {'id':'e','label':'Legacy','session':'old','host':'legacy.example.test','provider':'unspecified'},
  ];
  HostSearchFields fields(Map<String,String> row) => HostSearchFields(label:row['label']!,session:row['session']!,host:row['host']!,provider:row['provider']!);
  List<Map<String,String>> search(String query,{HostTaskFilter filter=HostTaskFilter.all}) => searchHostCatalog(entries,query:query,
    filter:filter,fields:fields,current:(row) => row['id']=='a' || row['id']=='c',history:(row) => row['id']=='b');
  test('name session address provider use case-insensitive trimmed contiguous substrings',() {
    for (final sample in {'  SAME maCH  ':'a,b','UILD W':'a','DEV.EXAMPLE':'b','100.64':'a',
      'Tailscale':'a','DIRECT':'b','EasyTier':'c','zeroTIER':'d','中文':'c','legacy.example':'e'}.entries) {
      _check(_ids(search(sample.key))==sample.value,'public search ${sample.key}');
    }
    _check(search('SameMachine').isEmpty,'inner spaces must remain meaningful');
    _check(search('Machine Build').isEmpty,'do not match across public fields');
    _check(search('a.*').isEmpty,'query must be literal, not regex');
  });
  test('only explicitly direct records match direct and private fields are excluded',() {
    _check(_ids(search('direct'))=='b','unspecified must not become direct');
    _check(search('unspecified').isEmpty,'unspecified is not a provider short name');
    _check(search('opaque-secret').isEmpty,'private/opaque fields must not enter search');
    _check(search('never-search').isEmpty,'extra fields must remain outside the projection');
  });
  test('bound network provider overrides declaration and a missing binding stays unknown',() {
    _check(hostSearchProvider('direct',hasBinding:true,boundProvider:'tailscale')=='tailscale','binding must override declaration');
    _check(hostSearchProvider('tailscale',hasBinding:true,boundProvider:'easytier')=='easytier','changed binding must be reflected');
    _check(hostSearchProvider('direct',hasBinding:true).isEmpty,'missing binding must not fall back to direct');
    _check(hostSearchProvider('unspecified',hasBinding:false)=='unspecified','unbound unspecified must remain unspecified');
    _check(hostSearchProvider('direct',hasBinding:false)=='direct','explicit unbound declaration');
    _check(hostNetworkDescription(declared:'tailscale',requiresBinding:false,hasBinding:false).contains('系统直连'), 'legacy label uses system route');
    _check(hostNetworkDescription(declared:'tailscale',requiresBinding:false,hasBinding:false).contains('仅为资料'), 'legacy provider is descriptive');
    final missing=hostNetworkDescription(declared:'direct',requiresBinding:false,hasBinding:true);
    _check(missing.contains('资料缺失') && !missing.contains('系统直连') && !missing.contains('null'), 'missing binding route must remain unknown');
    _check(hostNetworkDescription(declared:'tailscale',requiresBinding:true,hasBinding:false).contains('待绑定'), 'new profile must show binding requirement');
    _check(hostNetworkDescription(declared:'direct',requiresBinding:false,hasBinding:true,boundLabel:'Net',boundEnabled:false).contains('本机停用'), 'bound disabled network must be explicit');
  });
  test('same labels retain distinct original row identities and original priority order',() {
    final found=search('same');
    _check(_ids(found)=='a,b','order changed');
    _check(identical(found[0],entries[0]) && identical(found[1],entries[1]),'row objects replaced');
    final priority=searchHostCatalog([entries[1],entries[0]],query:'same',filter:HostTaskFilter.all,
      fields:fields,current:(_) => false,history:(_) => false);
    _check(_ids(priority)=='b,a','caller priority order was replaced by catalog order');
  });
  test('rapid input always uses current text without queued stale results',() {
    for (final sample in {'s':'a,b,c,e','sa':'a,b','same m':'a,b','no-match':'','中文':'c','':'a,b,c,d,e'}.entries) {
      _check(_ids(search(sample.key))==sample.value,'rapid query ${sample.key}');
    }
  });
  test('combined pending filter empty query and clear text keep pending selection',() {
    _check(_ids(search('same',filter:HostTaskFilter.current))=='a','combined result');
    _check(search('direct',filter:HostTaskFilter.current).isEmpty,'combined zero result');
    _check(_ids(search('',filter:HostTaskFilter.current))=='a,c','clearing text must preserve pending-only');
    _check(_ids(search('  ',filter:HostTaskFilter.current))=='a,c','whitespace-only query');
    _check(_ids(search(''))=='a,b,c,d,e','clearing all filters restores all rows');
  });
  test('historical filter intersects search and remains separate from current pending',() {
    _check(_ids(search('same',filter:HostTaskFilter.history))=='b','history intersection');
    _check(search('tailscale',filter:HostTaskFilter.history).isEmpty,'history must not include current');
    _check(_ids(search('',filter:HostTaskFilter.history))=='b','clear text must keep history condition');
    const target=HostSearchTarget('w1:p1','term_abcd','blocked');
    _check(historicalSearchTargets(const [target],fresh:true,current:true).isEmpty,'current is not history');
    _check(historicalSearchTargets(const [target],fresh:false,current:false).length==1,'stale blocked must be recheckable');
    _check(historicalSearchTargets(const [target],fresh:true,current:false).length==1,'noncurrent must be recheckable');
    _check(historicalSearchTargets(const [HostSearchTarget('w1:p1','term_abcd','unknown')],fresh:false,current:false).isEmpty,'unknown must not turn into historical blocked');
    _check(historicalSearchTargets(const [],fresh:false,current:false).isEmpty,'missing history is not a zero blocked assertion');
  });
  test('only fresh current explicitly blocked locatable targets count',() {
    const targets=[HostSearchTarget('w1:p1','term_abcd','blocked'),HostSearchTarget('w1:p2','term_1234','unknown')];
    _check(currentSearchTargets(targets,fresh:true,current:true).length==1,'known blocked target missing');
    for (final flags in [(false,true),(true,false),(false,false)]) {
      _check(currentSearchTargets(targets,fresh:flags.$1,current:flags.$2).isEmpty,'stale/unavailable must not count');
    }
    _check(currentSearchTargets(const [HostSearchTarget('w1:p1','term_abcd','unknown')],fresh:true,current:true).isEmpty,'unknown is not pending');
  });
  test('invalid and ambiguous pane or terminal pairs never count as pending',() {
    for (final targets in [
      const [HostSearchTarget('','term_abcd','blocked')],
      const [HostSearchTarget('w1:p1','term_unsafe value','blocked')],
      const [HostSearchTarget('w1:p1','term_abcd','blocked'),HostSearchTarget('w1:p1','term_abcd','blocked')],
      const [HostSearchTarget('w1:p1','term_abcd','blocked'),HostSearchTarget('w1:p1','term_1234','blocked')],
      const [HostSearchTarget('w1:p1','term_abcd','blocked'),HostSearchTarget('w1:p2','term_abcd','blocked')],
    ]) {
      _check(currentSearchTargets(targets,fresh:true,current:true).isEmpty,'ambiguous target admitted');
      _check(historicalSearchTargets(targets,fresh:false,current:false).isEmpty,'ambiguous historical target admitted');
    }
  });
  test('changing dashboard eligibility updates the same local query without reordering',() {
    final pending=<String>{'a'};
    List<Map<String,String>> visible() => searchHostCatalog(entries,query:'same',filter:HostTaskFilter.current,
      fields:fields,current:(row) => pending.contains(row['id']),history:(_) => false);
    _check(_ids(visible())=='a','initial pending');
    pending.clear();
    _check(visible().isEmpty,'stale report retained as pending');
    pending.add('b');
    _check(_ids(visible())=='b','new fresh report not reflected');
  });
}
