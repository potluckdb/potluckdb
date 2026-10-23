// better-sqlite3 13 targets Node-API version 10, whose references can hold any
// value. PotluckDB targets Node-API version 8 so that one binary also serves
// Node.js 20, which lacks version 10; there, references can only hold objects,
// functions and symbols. These types keep better-sqlite3's code unchanged
// where it keeps strings or arbitrary values alive.

#if NAPI_VERSION >= 10

typedef Napi::Reference<Napi::String> StringConstant;
inline StringConstant MakeStringConstant(Napi::Env env, const char* str) {
	return Napi::Persistent(InternalizedFromLatin1(env, str));
}

typedef Napi::Reference<Napi::Value> ValueReference;
inline ValueReference MakeValueReference(Napi::Value value) {
	return Napi::Persistent(value);
}

#else

// A string that is created again on each use, instead of being kept alive.
class StringConstant {
public:
	StringConstant() : env(NULL), str(NULL) {}
	StringConstant(napi_env env, const char* str) : env(env), str(str) {}
	inline Napi::String Value() const { return InternalizedFromLatin1(env, str); }
private:
	napi_env env;
	const char* str;
};
inline StringConstant MakeStringConstant(Napi::Env env, const char* str) {
	return StringConstant(env, str);
}

// A strong reference to any value, which it keeps in a one-element array.
// Like Napi::Reference, an all-zero instance is empty: SQLite zero-fills the
// aggregate accumulators that hold these, without running constructors.
class ValueReference {
public:
	ValueReference() : box() {}
	ValueReference(ValueReference&& other) : box(std::move(other.box)) {}
	ValueReference& operator=(ValueReference&& other) { box = std::move(other.box); return *this; }

	inline bool IsEmpty() const { return box.IsEmpty(); }

	inline Napi::Value Value() const {
		if (box.IsEmpty()) return Napi::Value();
		Napi::Object array = box.Value();
		napi_value result;
		if (napi_get_element(array.Env(), array, 0, &result) != napi_ok) return Napi::Value();
		return Napi::Value(array.Env(), result);
	}

	inline void Reset() { box.Reset(); }

	// Like Napi::Reference, but the reference is always strong.
	inline void Reset(const Napi::Value& value, uint32_t refcount = 1) {
		(void)refcount;
		napi_env env = value.Env();
		if (box.IsEmpty()) box.Reset(Napi::Array::New(env, 1), 1);
		napi_status status = napi_set_element(env, box.Value(), 0, value);
		assert(status == napi_ok); ((void)status);
	}

private:
	Napi::ObjectReference box;
};
inline ValueReference MakeValueReference(Napi::Value value) {
	ValueReference reference;
	reference.Reset(value, 1);
	return reference;
}

#endif
