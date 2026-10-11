// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <optional>
#include <string_view>

namespace coney {

/// The finite decimal number `text` spells in full (`-1.25`, `3`, `2e-3`), or nothing for anything else: an empty
/// text, a leading `+` or space, trailing characters, hexadecimal, infinity, NaN or a value out of range. The same
/// rules as std::from_chars on every platform, including Apple's libc++, which has no floating-point from_chars.
[[nodiscard]] std::optional<double> parseDecimal(std::string_view text);
} // namespace coney
