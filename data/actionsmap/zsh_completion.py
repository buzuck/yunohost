#!/usr/bin/python3
import os
import re
import sys
import yaml

# DOCS:
# - https://github.com/zsh-users/zsh/blob/master/Etc/completion-style-guide
# - http://zsh.sourceforge.net/Doc/Release/Completion-System.html#Completion-System
#   or `man zshcompsys`
# - http://zsh.sourceforge.net/Guide/zshguide06.html
#
# Misc:
# - http://zsh.sourceforge.net/Doc/Release/Parameters.html#Array-Parameters

# TODO:
# - use the extra:required:True pattern (similar to `nargs`?)
# - Have the global options listed in a separate category
# - Allow multiple arguments per option
#   (e.g.: `yunohost user info alice --fields uid cn mail`)
# - In `yunohost.yml`, consider merging:
#   - metavar
#   - pattern
#   - autocomplete
# - Make use of `type`, maybe using `_guard`
# - Use `pattern`, maybe with `_guard`. This seems hard though, as ZSH has
# its own globbing language...
# Link about this globbing system:
# http://zsh.sourceforge.net/Doc/Release/Expansion.html#Filename-Generation
#
# NOTES:
# - Command for debugging zsh: `unfunction _yunohost; autoload -U _yunohost`
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# - Optimization:
#   - caching mecanism: invalidate the cache afer some commands? Hard, the
#   cache is local to user
#   - implement a zstyle switch, to change the cache validity period?

THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONSMAP_FILE = THIS_SCRIPT_DIR + '/yunohost.yml'
ZSH_COMPLETION_FILE = THIS_SCRIPT_DIR + '/../zsh-site-functions/_yunohost'

if len(sys.argv) and sys.argv[1] == '--debug':
    ZSH_COMPLETION_FILE = sys.argv[2]

# This dict will contain the completion function data
COMPLETION_FUNCTIONS = {}


def main():
    yunohost_map = yaml.safe_load(open(ACTIONSMAP_FILE))
    output = CONST_HEADER
    #
    # Creation of the entry function of the completion script
    output += entry_point(yunohost_map)

    #
    # The main loop, going through all (sub)commands
    for key, value in yunohost_map.items():
        output += make_category(key, value)

    #
    # Building the auxilliary completion functions, they have been added
    # to this dict during the main loop
    output += build_completion_functions(COMPLETION_FUNCTIONS)
    output += CONST_END_OF_FILE

    with open(ZSH_COMPLETION_FILE, 'w') as _yunohost:
        _yunohost.write(output)


def entry_point(yunohost_map: dict) -> str:
    """
    Provides the entry point of the completion script: a function called _yunohost, along with the routing function.
    :param dict yunohost_map: The while YAML
    :return str: The resulting string
    """
    categories = ''

    # Remember the amount of spaces to get a human readable completion file
    spaces = re.search('\n(\s*)YNH_COMMANDS_DESCRIPTION', ENTRY_POINT).group(1)
    #
    # Going through the main ynh commands
    for category, content in yunohost_map.items():
        # We only consider a command an item that has a 'help' field
        if not 'category_help' in content:
            continue

        # Creation of the category line, with the right amount of spaces
        categories += '{}{}\n'.format(spaces, "'{}:{}'") \
            .format(category, _escape(content['category_help']))

    #
    # Generation of the global arguments, valid for any command
    global_options = make_argument_list(yunohost_map['_global'], ' '*8)

    return ENTRY_POINT \
        .replace('YNH_GLOBAL_OPTIONS', global_options) \
        .replace('YNH_COMMANDS_DESCRIPTION', categories)


def make_category(category_name: str, category_map: dict) -> str:
    """
    Generates the main function of a given category.
    Reminder:
        yunohost   monitor    info    --cpu --ram
           ^          ^         ^          ^
        (script) | category | action | parameters
    :param str category_name: The name of the category
    :param dict category_map: The mapping associated to the category
    :return str: The entry point of the given category
    """
    # No need to go further if a category does not have an `action` field
    if not 'actions' in category_map:
        return ''

    output = TEMPLATES['command']
    subcategories = ''

    # Memorizing the spaces, to get a human readable file
    spaces = re.search('\n(\s*)YNH_ACTIONS_DESCRIPTION', output).group(1)

    # First, complete the main action map
    for action, action_details in category_map['actions'].items():
        # Empty element failsafe
        if not 'action_help' in action_details and not 'arguments' in action_details:
            continue

        # Adding the new action to the map of the category
        output = output.replace(
            'YNH_ACTIONS_DESCRIPTION',
            '{} \\\n{}YNH_ACTIONS_DESCRIPTION'
                .format("'{}:{}'", spaces)
                .format(action, _escape(action_details['action_help']))
        )
        # Generation of this action completion function
        output += make_action(action, action_details).replace('COMMAND', category_name)

    # Removing the remaining tag, uneeded now
    output = re.sub('\n(\s*)YNH_ACTIONS_DESCRIPTION', '', output)

    #
    # Going through the subcategories if any
    #
    if 'subcategories' in category_map:
        # Getting the template, and saving the spaces
        subcategories = TEMPLATES['subcategory']
        spaces = re.search('\n(\s*)YNH_SUBCACTEGORIES_DESCRIPTION', subcategories).group(1)

        # Looping through the subcategories
        for subcategory, subcategory_details in category_map['subcategories'].items():

            subcategories = subcategories.replace(
                'YNH_SUBCACTEGORIES_DESCRIPTION',
                '{}\\\n{}YNH_SUBCACTEGORIES_DESCRIPTION'
                    .format("'{}:{}'", spaces)
                    .format(subcategory, _escape(subcategory_details['subcategory_help']))
            )
            # Creation of the subcategory
            output += make_category(category_name+'_'+subcategory, subcategory_details)

        # Removing the remaining tag, uneeded now
        subcategories = re.sub('\n(\s*)YNH_SUBCACTEGORIES_DESCRIPTION', '', subcategories)

    # Adding the subcategories to the final output.  `subcategories` may be
    # empty, if no subcategory exists for the current command.
    return output \
        .replace('YNH_SUBCATEGORY', subcategories) \
        .replace('COMMAND', category_name)


def make_action(action_name: str, action_map: dict) -> str:
    """
    Generates the completion function for a given action
    Reminder:
        yunohost   monitor    info    --cpu --ram
           ^          ^         ^          ^
        (script) | category | action | parameters
    :param str action_name: The name of the action
    :param dict action_map: The mapping associated to the action
    :return str: The entry point of the given category
    """
    # Return immediately if no argument is expected for this action
    if not 'arguments' in action_map:
        return TEMPLATES['action_without_arguments'].replace('ACTION', action_name)

    action = TEMPLATES['action']
    # Memorizing the spaces, to get a human readable file
    spaces = re.search('\n(\s*)YNH_ACTION', action).group(1)

    # Creation of the arguments list, and
    # Insertion of the action's name
    return action \
        .replace('YNH_ACTION', make_argument_list(action_map, spaces)) \
        .replace('ACTION', action_name)


def make_argument_list(action_map: dict, spaces: str=4*' ') -> str:
    """
    Builds the actions list.
    :param dict action_map: The list of possible arguments
    :param str spaces: [optional] The amount of spaces used for the indentation
    :return str: The arguments list, ready to use
    """
    action_list = 'YNH_ACTION'
    # This is a counter, in case of position dependent paremeters (the ones not
    # beginning with a `-`)
    position = 0

    for argument_name, argument_details in action_map['arguments'].items():
        #
        # Initializing the argument dict to make sure all fields are defined
        # - id: identifier (`-n` or `--name`). If none (e.g. `ynh app install
        # APP_NAME`), this field is the arguments position or cardinality (from
        # `nargs`)
        # - excludes: usually the argument itself. Only used for optional args
        # - desc: the argument description
        # - completion: the completion function name
        #
        arg = {'id': '', 'excludes': '', 'desc': '', 'completion': ''}

        #
        # Forcing to str, as the yaml parser inteprets numbers as integers
        # (eg.: `firewall allow... -4`)
        argument_name = str(argument_name)

        #
        # A parameter not beginning with `-` is considered mandatory.
        if argument_name[0] != '-':
            position += 1
            # This parameter may be used more than once, else we use the position counter
            if 'nargs' in argument_details and argument_details['nargs'] in '+*':
                arg['id'] = '*'
            else:
                arg['id'] = str(position)
            arg['desc'] = argument_details['help'] if 'help' in argument_details \
                    else argument_name
        # ----
        # NOTE: a double colon marks for an optional argument:
        # '::Username to update:__ynh_user_list'
        # ----

        #
        # This is an optional parameter, beginning with a `-`
        else:
            # `full` is the extended form of the argument (e.g.: -n is short for --number)
            if 'full' in argument_details:
                arg['id'] = "'{{{},{}}}'".format(argument_name, argument_details['full'])
                arg['excludes'] = '({} {})'.format(argument_name, argument_details['full'])
            else:
                arg['id'] = argument_name
            if 'nargs' in argument_details and argument_details['nargs'] in '+*':
                # Trickery: using `excludes` as a cardinality indicator
                arg['excludes'] = '*'
            # The description of the parameter
            # Getting the `help` field if any, else simply by using it's name
            arg['desc'] = (argument_details['help'] if 'help' in argument_details
                    else str(argument_details['full']).lstrip('--')
                ) + arg['completion']
            #
            # If defined, add the default value as a hint
            if 'default' in argument_details:
                arg['desc'] += ' (default: {})'.format(argument_details['default'])


        #
        # Generation of the completion hints
        #
        arg['completion'] = make_argument_completion(argument_details)

        # The presence of any of these shows that this parameter expects an argument
        if 'extra' in argument_details or \
                'nargs' in argument_details or \
                'type' in argument_details or \
                'choices' in argument_details:
            placeholder = "'{}{}{}:{}:{}'"
        else:
            # No argument needed
            placeholder = "'{}{}{}'"

        #
        # Putting it all together
        arg['desc'] = _escape(arg['desc'])
        action_list = action_list.replace(
            'YNH_ACTION',
            '{} \\\n{}YNH_ACTION'
            .format(placeholder, spaces)
            .format(
                arg['excludes'],
                arg['id'],
                # Lets assume any id has at least 2 characters
                '['+arg['desc']+']' if len(arg['id']) > 1 else '',
                # Those two items will only be inserted if the placeholder has
                # the corresponding slots
                arg['desc'],
                arg['completion']
            )
        )
    # Removing the extra tag and backslash,
    return re.sub(r'\s*\\\n(\s*)YNH_ACTION', '', action_list)


def make_argument_completion(argument_details: dict) -> str:
    """
    Finds the completion function for the given argument, if defined.
    :param dict argument_details: The mapping of the argument
    :return str: The name of the completion function, or an empty string
    """
    # `COMPLETION_FUNCTIONS` hold the elements needed to generate it.  The
    # actual creation of this function will be done by build_completion_functions(),
    # called near the end of this script.

    #
    # An autocompletion function is defined
    if 'extra' in argument_details and 'autocomplete' in argument_details['extra']:
        autocomplete = argument_details['extra']['autocomplete']

        #
        # This is a combinaision of YunoHost and jq commands
        #
        if 'ynh_selector' in autocomplete and 'jq_selector' in autocomplete:
            # Create this function's name
            function_name = _remove_special_chars(
                    '__ynh_' + _norm_name(autocomplete['ynh_selector'])
            )
            #
            # Add it to the function's dict, if it has not been created yet
            if not function_name in COMPLETION_FUNCTIONS:
                # First, build the shell command that returns the completions
                call = "yunohost {} --output-as json | jq -cr '{}'".format(
                    autocomplete['ynh_selector'],
                    autocomplete['jq_selector']
                )
                # If a cache is needed, wrap the call in the caching function
                if 'use_cache' in autocomplete:
                    call = '__get_ynh_cache \'YNH_{}\' "{}"'.format(
                        _norm_name(autocomplete['ynh_selector']), call
                    )
                # Lastly, save the content
                COMPLETION_FUNCTIONS[function_name] = {'shell_call': call}
            return function_name

        #
        # The autocompletion is done by a grep
        #
        elif 'shell_call' in autocomplete:
            # Create this function's name
            function_name = _remove_special_chars(
                    '__ynh_' + _norm_name(autocomplete['shell_call'])
            )
            #
            # Add it to the function's dict, if it has not been created yet
            if not function_name in COMPLETION_FUNCTIONS:
                # First, build the shell command that returns the completions
                call = autocomplete['shell_call']

                # If a cache is needed, wrap the call in the caching function
                # Note: not tested with grep, only with YunoHost's commands
                if 'use_cache' in autocomplete:
                    call = '__get_ynh_cache \'YNH_{}\' "{}"'.format(
                        _remove_special_chars(autocomplete['shell_call']), call
                    )
                # Lastly, save the content
                COMPLETION_FUNCTIONS[function_name] = {'shell_call': call}
            return function_name

        #
        # This is a combinaision of two other completion functions
        #
        elif 'aggregate' in autocomplete:
            # Create this function's name
            function = '__ynh'
            for subcall in autocomplete['aggregate']:
                function += '_' + _norm_name(subcall['ynh_selector'])

            # If this function is yet undefined, create it
            if not function in COMPLETION_FUNCTIONS:
                aggregation = ''
                for subcall in autocomplete['aggregate']:
                    aggregation += "\n'{}:{}:{}' \\".format(
                        subcall['name'],
                        subcall['name'],
                        _norm_name('__ynh_'+subcall['ynh_selector'])
                    )
                # Saving the result, and removing the extra backslash
                COMPLETION_FUNCTIONS[function] = {'aggregated': aggregation}
            return function

        #
        # The autocompletion is done by a ZSH function
        #
        elif 'zsh_completion' in autocomplete:
            return autocomplete['zsh_completion']

    #
    # `choices` and `autocomplete` should not be present at the same time
    #
    elif 'choices' in argument_details:
        return '({})'.format(' '.join(argument_details['choices']))

    return ''


def build_completion_functions(functions: dict) -> str:
    """
    Generates the custom completion functions for YunoHost, from the "metavar"
    object of the YAML mapping.
    :param dict metavars: The 'metavar' object from the YAML
    :return str: All custom completion functions, beginning by '__ynh_'
    """
    output = ''

    #
    # This basically consists in associating the type of the completion
    # function to it's template
    for function, completion in functions.items():

        if 'aggregated' in completion:
            output += TEMPLATES['completion_function_aggregate'] \
                .replace('FUNCTION',   function) \
                .replace('AGGREGATED', completion['aggregated'])
        else:
            output += TEMPLATES['completion_shell_call'] \
                .replace('FUNCTION',   function) \
                .replace('SHELL_CALL', completion['shell_call'])

    return output


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
#
# Utility functions, mainly string manipulation
#

def _norm_name(string: str) -> str:
    """
    Normalizies a string to make it look like a function name:\
      - lowercase
      - spaces replaced by underscores
      - no dashs
    :param str string: the string to norm.
    :return str: The normed string
    """
    return string.lower() \
        .replace(' ', '_') \
        .replace('-', '') \
        .replace('/', '_') \
        .replace('.', '_')


def _escape(string: str) -> str:
    """
    Escapes any special character:
     - single quotes (') are put in a separate double quoted string ('"'"')
     - colons (:) and other characters are preceded by a backslash (\:)
    :param str string: The string to escape
    :return str: `string` escaped
    """
    return string \
        .replace("'", "'\"'\"'") \
        .replace(':', r'\:')


def _remove_special_chars(string: str) -> str:
    """
    Removes any character with a special meaning in ZSH, such as `$`, `{` ...
    :param str string: The string to clean
    :return str: `string` cleaned
    """
    # NOTE: this list may not be comprehensive and should be extended if needed
    return re.sub(r'[- =\^+:\?\'"$(){}\[\]/\\\\]', '', string).replace('.', '')


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
#
# The ZSH templates are defined below
#

CONST_HEADER = r'''#compdef yunohost
# -----------------------------------------------------------------------------
# Description
# -----------
#  Completion script for yunohost, automatically generated from the action map
#  decribed by `yunohost.yml`
# -----------------------------------------------------------------------------

local state line curcontext

# For debug purposes only
__log() {
    echo $@ >> '/tmp/zsh-completion.log'
}

# First argument: The name of the completion list
# 2nd argument:   The command to get it
# (( $+functions[__get_ynh_cache] )) ||
function __get_ynh_cache() {
    # Checking a global cache policy is defined,
    # and linkage to ynh-cache-policy
    local update_policy completion_items
    zstyle -s ":completion:${curcontext}:" cache-policy update_policy
    if [[ -z "$update_policy" ]]; then
        zstyle ":completion:${curcontext}:" cache-policy __yunohost_cache_policy
    fi
    # If the cache is invalid (too old), regenerate it
    if _cache_invalid $1 || ! _retrieve_cache $1; then
        completion_items=(`eval $2`)
        _store_cache $1 completion_items
    else
        _retrieve_cache $1
    fi
    echo $completion_items
}
# (( $+functions[__yunohost_cache_policy] )) ||
__yunohost_cache_policy(){
    local cache_file="$1"
    # Rebuild if the yunohost executable is newer than cache
    [[ "${commands[yunohost]}" -nt "${cache_file}" ]] && return

    # Rebuild if cache is more than a week old
    local -a oldp
    # oldp=( "$1"(mM+1) ) # month
    oldp=( "$1"(Nm+7) ) # week
    (( $#oldp )) && return
    return 1
}


#
# Routing function, used to go through $words and find the correct subfunction
# (Suggestions welcome to improve that design... =/ )
# (( $+functions[__jump] )) ||
function __jump() {
    local cmd

    # Remember the subcommand name
    if (( ${#@} == 0 )); then
        local cmd=${words[2]}
    else
        cmd=$1 # < no more used?
    fi

    # Set the context for the subcommand
    ynhcommand="${ynhcommand}_${cmd}"
    # Narrow the range of words we are looking at to exclude `yunohost`
    (( CURRENT-- ))
    shift words
    # Run the completion for the subcommand
    if ! _call_function ret ${ynhcommand#:*:}; then
        _default && ret=0
    fi
    return ret
}

'''

# --------------- Main entry point -----------------------------------
ENTRY_POINT = r'''
# (( $+functions[_yunohost] )) ||
function _yunohost() {
    local curcontext="${curcontext}" state line ret=1
    local mode
    # `ynhcommand` is where `__jump` builds the name of the completion function
    ynhcommand='_yunohost'

    typeset -ag common_options; common_options=(
        YNH_GLOBAL_OPTIONS
    )

    if (( CURRENT > 2 )); then
        __jump
    else
        local -a yunohost_categories; yunohost_categories=(
            YNH_COMMANDS_DESCRIPTION )
        _describe -V -t yunohost-commands 'yunohost category' yunohost_categories "$@"
    fi

    _arguments -s -C $common_options
    # unset common_option
}
'''


CONST_END_OF_FILE = r'''
_yunohost "$@"
'''


TEMPLATES = {
    'command':
        r'''

#-----------------------------------------
#               COMMAND
#-----------------------------------------

# (( $+functions[_yunohost_COMMAND] )) || \
function _yunohost_COMMAND() {
    if (( CURRENT > 2 )); then
        __jump
    else
        local -a yunohost_COMMAND; yunohost_COMMAND=(
            YNH_ACTIONS_DESCRIPTION
        )
        _describe -V -t yunohost-COMMAND 'yunohost COMMAND category' yunohost_COMMAND "$@"
        YNH_SUBCATEGORY
    fi
}
''',

    # --------------------------------------------------------------------
    'subcategory':
        r'''
        local -a yunohost_COMMAND_subcategories; yunohost_COMMAND_subcategories=(
            YNH_SUBCACTEGORIES_DESCRIPTION
        )
        _describe -V -t yunohost-COMMAND-subcategories 'yunohost COMMAND subcategories' yunohost_COMMAND_subcategories "$@"
''',

    # --------------------------------------------------------------------
    # Note: The common_options are not added until we find a way to have them
    # in a separate category.  It is too confusing to have them mixed with
    # the command's options.
    # Memo:
    # YNH_ACTION \
    # $common_options
    #
    'action':
        r'''
# (( $+functions[_yunohost_COMMAND_ACTION] )) ||
function _yunohost_COMMAND_ACTION() {
    _arguments -s -C \
        YNH_ACTION
}

''',

    # --------------------------------------------------------------------
    'action_without_arguments':
        r'''
# (( $+functions[_yunohost_COMMAND_ACTION] )) ||
function _yunohost_COMMAND_ACTION() { }

''',

    # --------------------------------------------------------------------
    'completion_shell_call':
        r'''
# (( $+functions[FUNCTION] )) ||
function FUNCTION() {
    compadd "$@" -- ${(@)$(SHELL_CALL)}
}
''',

    # --------------------------------------------------------------------
    'completion_function_aggregate':
    # The newline is included in `AGGREGATED`
        r'''
# (( $+functions[FUNCTION] )) ||
function FUNCTION() {
    _alternative \AGGREGATED
}
'''

}


main()