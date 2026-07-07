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
