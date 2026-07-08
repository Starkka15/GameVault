# GameVault RPG Maker — Win32API compatibility shim (mkxp-z preloadScript)
#
# Many RPG Maker VX Ace/XP games call Win32API to reach Windows-only DLLs for
# cosmetic features: screenshots (gdiplus.dll), window resizing (user32.dll),
# GUID generation (rpcrt4.dll), etc. On Windows RPG Maker these just load; under
# mkxp-z on Linux there is no such DLL and Win32API.new RAISES at script-load
# time, killing the whole game before the title screen.
#
# This preload wraps Win32API so a failed DLL/function load degrades to a no-op
# that returns 0, instead of crashing. The Windows-only feature silently does
# nothing (mkxp-z manages its own window, and screenshots are non-essential),
# but the game boots and plays. Functions that DO resolve are untouched.
# --- Ruby 1.9 compatibility (mkxp-z bundles Ruby 3.1) ---
# RPG Maker VX Ace shipped Ruby 1.9, which had the uppercase boolean/nil
# constants TRUE/FALSE/NIL. Ruby 2.4 deprecated them and 3.x removed them, so
# legacy scripts that write `TRUE`/`FALSE`/`NIL` die at load with a NameError
# (e.g. "uninitialized constant CP::COMPOSITE::TRUE"). Redefine at top level so
# they resolve everywhere via Object constant lookup.
TRUE  = true  unless defined?(TRUE)
FALSE = false unless defined?(FALSE)
NIL   = nil   unless defined?(NIL)

if defined?(Win32API)
  class Win32API
    alias_method :__gv_orig_initialize, :initialize
    def initialize(*args)
      @__gv_dead = false
      begin
        __gv_orig_initialize(*args)
      rescue Exception
        @__gv_dead = true
      end
    end

    alias_method :__gv_orig_call, :call
    def call(*args)
      return 0 if @__gv_dead
      __gv_orig_call(*args)
    end
    alias_method :Call, :call rescue nil
  end
end
