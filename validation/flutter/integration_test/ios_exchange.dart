import 'dart:convert';
import 'dart:io';

/// Creates the owned exchange exactly once; an existing directory is never reused.
void initializeIosExchange(Directory directory, Map<String, Object> baseline) {
  if (directory.existsSync())
    throw StateError('direct_ssh_ios_exchange_exists');
  directory.createSync(recursive: true);
  final pending = File('${directory.path}/semantics-baseline.json.pending')
    ..writeAsStringSync(jsonEncode(baseline), flush: true);
  pending.renameSync('${directory.path}/semantics-baseline.json');
}
