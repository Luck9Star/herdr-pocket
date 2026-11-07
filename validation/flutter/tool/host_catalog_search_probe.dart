import 'dart:convert';
import '../test/host_catalog_search_cases.dart';

void main() {
  final checks=<String>[];
  hostCatalogSearchCases((name,body) { body(); checks.add(name); });
  print(jsonEncode({'scope':'actual pure Dart host search/filter core; no Flutter widgets, SSH or device proof',
    'passed':checks.length,'checks':checks}));
}
