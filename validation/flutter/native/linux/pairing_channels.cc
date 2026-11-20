#include "pairing_channels.h"

#include "host_catalog_file.h"
#include "identity.h"

#include <array>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#include <unistd.h>

namespace {

constexpr char kApp[] = "herdr-pocket.flutter";
enum class Action { Reserve, Create, Public, Sign, Delete, Load, Save };

struct Request {
  Request(FlMethodCall* method, Action command) : call(FL_METHOD_CALL(g_object_ref(method))), action(command) {}
  ~Request() { g_object_unref(call); }
  FlMethodCall* call;
  Action action;
  std::string handle, expected, contents, result;
  std::vector<uint8_t> payload;
  std::array<uint8_t, 64> signature{};
  const char* error = nullptr;
};

const char* IdentityError(int status) {
  switch (status) {
    case 0: return nullptr;
    case 2: return "device_key_missing";
    case 3: return "device_key_locked";
    case 4: return "device_key_store_unavailable";
    case 5: return "device_key_write_unknown";
    case 6: return "signature_limit";
    case 7: return "device_key_handle_exists";
    default: return "device_key_unavailable";
  }
}

void Run(GTask* task, gpointer, gpointer data, GCancellable*) {
  auto& request = *static_cast<Request*>(data);
  const char* handle = request.handle.c_str();
  std::array<char, 128> public_key{};
  switch (request.action) {
    case Action::Reserve: {
      std::array<char, 33> reserved{};
      request.error = IdentityError(hp_identity_reserve(reserved.data()));
      if (!request.error) request.result = reserved.data();
      break;
    }
    case Action::Create:
      request.error = IdentityError(hp_identity_create_reserved(kApp, handle, public_key.data()));
      if (!request.error) request.result = public_key.data();
      break;
    case Action::Public:
      request.error = IdentityError(hp_identity_public(kApp, handle, public_key.data()));
      if (!request.error) request.result = public_key.data();
      break;
    case Action::Sign: {
      const uint8_t empty = 0;
      const auto* payload = request.payload.empty() ? &empty : request.payload.data();
      request.error = IdentityError(hp_identity_sign(kApp, handle, payload, request.payload.size(), request.signature.data()));
      break;
    }
    case Action::Delete:
      request.error = IdentityError(hp_identity_delete(kApp, handle));
      break;
    case Action::Load: {
      herdr::CatalogRead loaded;
      if (herdr::LoadCatalog(g_get_user_data_dir(), &loaded)) {
        request.result = std::move(loaded.revision);
        request.contents = std::move(loaded.contents);
      } else {
        request.error = "catalog_unavailable";
      }
      break;
    }
    case Action::Save:
      if (!herdr::SaveCatalog(g_get_user_data_dir(), request.expected, request.contents, &request.result)) {
        request.error = "catalog_unavailable";
      }
      break;
  }
  g_task_return_boolean(task, TRUE);
}

void Reply(GObject*, GAsyncResult* result, gpointer) {
  auto* task = G_TASK(result);
  const auto& request = *static_cast<Request*>(g_task_get_task_data(task));
  if (!g_task_propagate_boolean(task, nullptr)) return;
  if (request.error) {
    fl_method_call_respond_error(request.call, request.error, nullptr, nullptr, nullptr);
    return;
  }
  g_autoptr(FlValue) value = nullptr;
  if (request.action == Action::Sign) {
    value = fl_value_new_uint8_list(request.signature.data(), request.signature.size());
  } else if (request.action == Action::Load) {
    value = fl_value_new_map();
    fl_value_set_string_take(value, "revision", fl_value_new_string(request.result.c_str()));
    fl_value_set_string_take(value, "contents", fl_value_new_string(request.contents.c_str()));
  } else if (request.action != Action::Delete) {
    value = fl_value_new_string(request.result.c_str());
  }
  fl_method_call_respond_success(request.call, value, nullptr);
}

void Dispatch(std::unique_ptr<Request> request) {
  g_autoptr(GTask) task = g_task_new(nullptr, nullptr, Reply, nullptr);
  g_task_set_task_data(task, request.release(), [](gpointer data) { delete static_cast<Request*>(data); });
  g_task_run_in_thread(task, Run);
}

const char* StringArgument(FlValue* args, const char* key) {
  FlValue* value = fl_value_lookup_string(args, key);
  return value && fl_value_get_type(value) == FL_VALUE_TYPE_STRING ? fl_value_get_string(value) : nullptr;
}

bool MapOfSize(FlValue* value, size_t size) {
  return value && fl_value_get_type(value) == FL_VALUE_TYPE_MAP && fl_value_get_length(value) == size;
}

void DeviceKeyCall(FlMethodChannel*, FlMethodCall* call, gpointer) {
  const std::string_view method(fl_method_call_get_name(call));
  Action action;
  if (method == "reserve") action = Action::Reserve;
  else if (method == "createReserved") action = Action::Create;
  else if (method == "public") action = Action::Public;
  else if (method == "sign") action = Action::Sign;
  else if (method == "delete") action = Action::Delete;
  else { fl_method_call_respond_not_implemented(call, nullptr); return; }
  auto request = std::make_unique<Request>(call, action);
  if (action != Action::Reserve) {
    FlValue* args = fl_method_call_get_args(call);
    const char* handle = MapOfSize(args, action == Action::Sign ? 2 : 1) ? StringArgument(args, "handle") : nullptr;
    if (!handle || strnlen(handle, 33) != 32) {
      fl_method_call_respond_error(call, "device_key_unavailable", nullptr, nullptr, nullptr);
      return;
    }
    request->handle = handle;
    if (action == Action::Sign) {
      FlValue* payload = fl_value_lookup_string(args, "payload");
      if (!payload || fl_value_get_type(payload) != FL_VALUE_TYPE_UINT8_LIST || fl_value_get_length(payload) > 65536) {
        fl_method_call_respond_error(call, "signature_limit", nullptr, nullptr, nullptr);
        return;
      }
      const auto count = fl_value_get_length(payload);
      if (count) {
        const uint8_t* bytes = fl_value_get_uint8_list(payload);
        request->payload.assign(bytes, bytes + count);
      }
    }
  }
  Dispatch(std::move(request));
}

int pairing_lease = -1;
std::string pairing_token;
void CatalogCall(FlMethodChannel*, FlMethodCall* call, gpointer) {
  const std::string_view method(fl_method_call_get_name(call));
  if (method == "acquirePairingLease") {
    if (pairing_lease >= 0 || (pairing_lease = herdr::AcquirePairingLease(g_get_user_data_dir())) < 0) {
      fl_method_call_respond_error(call, "pairing_operation_busy", nullptr, nullptr, nullptr); return;
    }
    g_autofree gchar* token = g_uuid_string_random(); pairing_token = token;
    g_autoptr(FlValue) value = fl_value_new_string(pairing_token.c_str());
    fl_method_call_respond_success(call, value, nullptr);
  } else if (method == "releasePairingLease") {
    FlValue* args = fl_method_call_get_args(call);
    const char* token = MapOfSize(args, 1) ? StringArgument(args, "token") : nullptr;
    if (!token || pairing_lease < 0 || pairing_token != token) {
      fl_method_call_respond_error(call, "pairing_operation_busy", nullptr, nullptr, nullptr); return;
    }
    close(pairing_lease); pairing_lease = -1; pairing_token.clear();
    fl_method_call_respond_success(call, nullptr, nullptr);
  } else if (method == "load") {
    Dispatch(std::make_unique<Request>(call, Action::Load));
  } else if (method == "save") {
    FlValue* args = fl_method_call_get_args(call);
    const char* expected = MapOfSize(args, 2) ? StringArgument(args, "expected") : nullptr;
    const char* contents = expected ? StringArgument(args, "contents") : nullptr;
    if (!contents || strnlen(expected, 65) > 64 || strnlen(contents, herdr::kMaxCatalogBytes + 1) > herdr::kMaxCatalogBytes) {
      fl_method_call_respond_error(call, "catalog_unavailable", nullptr, nullptr, nullptr);
      return;
    }
    auto request = std::make_unique<Request>(call, Action::Save);
    request->expected = expected;
    request->contents = contents;
    Dispatch(std::move(request));
  } else {
    fl_method_call_respond_not_implemented(call, nullptr);
  }
}

void Register(FlBinaryMessenger* messenger, const char* name, FlMethodChannelMethodCallHandler handler) {
  g_autoptr(FlStandardMethodCodec) codec = fl_standard_method_codec_new();
  g_autoptr(FlMethodChannel) channel = fl_method_channel_new(messenger, name, FL_METHOD_CODEC(codec));
  fl_method_channel_set_method_call_handler(channel, handler, nullptr, nullptr);
}

}  // namespace

void RegisterHerdrLinuxPairingChannels(FlBinaryMessenger* messenger) {
  Register(messenger, "dev.herdr/device-keys", DeviceKeyCall);
  Register(messenger, "dev.herdr/host-catalog", CatalogCall);
}
