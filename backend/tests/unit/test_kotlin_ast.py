from app.analyzers.common.kotlin_ast import KotlinFile, decode_string_literal


def kf(src: str) -> KotlinFile:
    return KotlinFile.parse("T.kt", src)


def test_decode_simple_template_parts():
    f = kf('fun a(x: String) { val s = "Bearer $access-${b.c} x" }')
    lit = f.find_all("string_literal")[0]
    parts = decode_string_literal(lit, f.src)
    assert parts == [("text", "Bearer "), ("expr", "access"), ("text", "-"), ("expr", "b.c"), ("text", " x")]


def test_decode_escapes():
    f = kf(r'val s = "a\"b\n\$c"')
    parts = decode_string_literal(f.find_all("string_literal")[0], f.src)
    assert parts == [("text", 'a"b\n$c')]


def test_resolve_concatenation_of_locals():
    f = kf(
        """
class W {
    fun build(): String {
        val series = "abc_"
        val grant = "XYZ123"
        val access = series + grant
        return access
    }
}
"""
    )
    fn = f.functions()[0]
    r = f.resolver_for(fn)
    v = r.resolve_name("access")
    assert v.value == "abc_XYZ123"
    assert v.literal_lines == {4, 5}


def test_resolve_file_and_class_constants_and_templates():
    f = kf(
        """
const val PREFIX = "pre"
class C {
    private val mid = "mid"
    fun g() {
        val s = "${PREFIX}-$mid-end"
    }
}
"""
    )
    r = f.resolver_for(f.functions()[0])
    assert r.resolve_name("s").value == "pre-mid-end"


def test_resolve_transforms():
    f = kf(
        """
fun g() {
    val a = listOf("ab", "cd").joinToString("")
    val b = StringBuilder().append("x1").append("y2").toString()
    val c = "%s-%s".format("p", "q")
    val d = String.format("%s%s", "m", "n")
    val e = "olleh".reversed()
    val h = "  pad  ".trim()
    val i = "LOW".lowercase()
    val j = String(Base64.getDecoder().decode("c2VjcmV0"))
}
"""
    )
    r = f.resolver_for(f.functions()[0])
    assert r.resolve_name("a").value == "abcd"
    assert r.resolve_name("b").value == "x1y2"
    assert r.resolve_name("c").value == "p-q"
    assert r.resolve_name("d").value == "mn"
    assert r.resolve_name("e").value == "hello"
    assert r.resolve_name("h").value == "pad"
    assert r.resolve_name("i").value == "low"
    assert r.resolve_name("j").value == "secret"


def test_unresolvable_parameter_returns_none():
    f = kf("fun g(p: String) { val s = p + \"x\" }")
    assert f.resolver_for(f.functions()[0]).resolve_name("s") is None


def test_function_annotations_and_params():
    f = kf(
        """
@RestController
@RequestMapping("/api/x")
class Ctl(private val reader: Reader) {
    @GetMapping("/items/{id}")
    fun get(@PathVariable id: Long, principal: Principal): String = reader.read(id)
}
"""
    )
    cls = f.classes()[0]
    assert cls.name == "Ctl"
    assert {a.name for a in cls.annotations} == {"RestController", "RequestMapping"}
    assert cls.annotations[1].first_string_arg() == "/api/x"
    assert cls.constructor_fields == {"reader": "Reader"}
    fn = cls.functions[0]
    assert fn.name == "get"
    assert [(p.name, p.type_name, [a.name for a in p.annotations]) for p in fn.params] == [
        ("id", "Long", ["PathVariable"]),
        ("principal", "Principal", []),
    ]
    assert fn.annotations[0].first_string_arg() == "/items/{id}"
