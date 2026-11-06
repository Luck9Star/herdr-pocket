package dev.herdr.pocket

/** Pure local admission test: no Android, JNI, credentials or activity. */
fun main() {
    val gate = LoginReviewGate()
    var checks = 0
    fun check(value: Boolean) { if (!value) error("login gate assertion $checks"); checks++ }
    gate.foreground(true)
    val first = gate.invalidate()
    check(gate.install(first, "review-1"))
    check(gate.capture("review-1") == first)
    check(gate.capture("review-2") == null)
    gate.foreground(false)
    check(gate.admit() == null)
    check(!gate.active(first))
    check(!gate.valid(first, "review-1"))
    check(!gate.install(first, "review-1"))
    gate.foreground(true)
    check(gate.capture("review-1") == null)
    val second = gate.admit()!!
    check(gate.install(second, "review-2"))
    check(!gate.valid(first, "review-1"))
    val third = gate.invalidate()
    check(!gate.install(second, "review-2"))
    check(gate.install(third, "review-3"))
    check(gate.valid(third, "review-3"))
    check(!gate.valid(third, "review-2"))
    gate.invalidate()
    check(!gate.valid(third, "review-3"))
    println("Kotlin login gate: $checks checks passed; synthetic JVM only")
}
