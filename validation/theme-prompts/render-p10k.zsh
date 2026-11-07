# Only invoked as zsh -dfi with a freshly created HOME/ZDOTDIR and clean env.
typeset -g POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true
typeset -g POWERLEVEL9K_INSTANT_PROMPT=off
typeset -g POWERLEVEL9K_DISABLE_GITSTATUS=true
typeset -g POWERLEVEL9K_MODE=nerdfont-v3
typeset -ga POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir prompt_char)
typeset -ga POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()
typeset -g POWERLEVEL9K_PROMPT_ADD_NEWLINE=false
typeset -g POWERLEVEL9K_DIR_BACKGROUND=4
typeset -g POWERLEVEL9K_DIR_FOREGROUND=7
typeset -g POWERLEVEL9K_DIR_VISUAL_IDENTIFIER_EXPANSION=$'\uf07b'
typeset -g POWERLEVEL9K_SHORTEN_STRATEGY=truncate_to_last
typeset -g POWERLEVEL9K_SHORTEN_DIR_LENGTH=1
COLUMNS=40 LINES=3
source "$1/powerlevel10k.zsh-theme"
for precmd in $precmd_functions; do $precmd; done
# Expand the engine-created shell PROMPT into the same ANSI text Zsh displays.
print -rnP -- "$PROMPT"
