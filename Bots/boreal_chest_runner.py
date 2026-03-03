from Py4GWCoreLib import *
from inspect import getframeinfo, stack
from typing import Callable
from enum import IntEnum

# NB: Make sure to keep these IDs up to date.
# Model IDs can shift with game updates.
class Creatures(IntEnum):
    MOUNTAIN_PINESOUL = 6539
    MOUNTAIN_ALOE = 6540
    AVALANCHE = 6528

#region Config classes
class PathPoints:
    def __init__(self):
        self.resign_point = (5480, -27913)
        self.path_points_to_exit_outpost = [(8180.0, -27084.0), (4790.0, -27870.0)]
        self.path_points_to_exit_outpost_after_resign = [(4790.0, -27870.0)]
        self.path_points_to_reenter_outpost = [(4760.0, -27845.0)]
        self.path_points_to_exit_outpost_after_merchant = [(5344.0, -27895.0), (4790.0, -27870.0)]
        self.path_points_to_look_for_chest =  [(2928.0, -24873.0), (2724.0, -22040.0), (-371.0, -20086.0), (-3294.0, -18164.0), (-5267.0, -14941.0), (-5297.0, -11045.0), (-1969.0, -12627.0), (1165.0, -14245.0), (4500.0, -15830.0), (5754.0, -15270.0)]

class InventoryConfig:
    def __init__(self):
        self.leave_free_slots = 5
        self.keep_id_kit = 2
        self.keep_gold_amount = 5000
        self.rare_items_to_keep = [ 
            RareItems.GLACIAL_BLADE, 
            RareItems.GLACIAL_BLADE_PURPLE, 
            RareItems.GLACIAL_BLADES,
            RareItems.DARKSTEEL_LONGBOW
        ]

class SellConfig:
    def __init__(self):
        self.sell_materials = True
        
class IDConfig:
    def __init__(self):
        self.id_purples = True
        self.id_golds = True

# Double check these rare item IDs are correct after recent game updates, otherwise the bot will salvage them.
class RareItems(IntEnum):
    GLACIAL_BLADE = 2473
    GLACIAL_BLADE_PURPLE = 2509
    GLACIAL_BLADES = 2474
    DARKSTEEL_LONGBOW = 2472
#endregion

#region Helpers
class BodyBlockHelper:
    def __init__(self):
        self.prev_pos : tuple[float, float] | None = None
        self.last_move_time : float = 0.0
        self.stuck = False

    def body_block_detected(self, seconds: float = 3.0, logger: Optional[Callable[[str], None]] = None):
        nearby_enemies = Routines.Agents.GetNearestEnemy(Range.Touch.value)
        nearby_chests = Routines.Agents.GetNearestChest(int(Range.Touch.value))

        # Bot can get stuck on enemies, and on very rare occasion on chests.
        if not (nearby_enemies or nearby_chests):
            return False
        
        timestamp = time.time()

        pos = Player.GetXY()
        if not pos:
            return False
    
        if not self.prev_pos:
            self.prev_pos = pos
            self.last_move_time = timestamp
            return False

        if Utils.Distance(pos, self.prev_pos) > 50:
            self.prev_pos = pos
            self.last_move_time = timestamp
            return False

        stuck = timestamp - self.last_move_time >= seconds
        if stuck:
            self.stuck = True
            if logger:
                logger("Body block detected.")

        return stuck
    
    def reset(self):
        self.prev_pos = None
        self.last_move_time = 0.0
        self.stuck = False

class LogLevel(IntEnum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3

class RunStats:
    def __init__(self):
        self.chests_found = 0
        self.chests_per_hour = 0.0
        self.average_chests_per_run = 0.0
        self.total_gold_earned = 0
        self.total_gold_items_identified = 0
        self.total_items_salvaged = 0
        self.start_time = time.time()
        self.last_chest_time = 0.0
        self.runs_completed = 0

        self.zero_chest_cnt = 0
        self.one_chest_cnt = 0
        self.two_chest_cnt = 0
        self.three_chest_cnt = 0

        self.zero_chest_pct = 0.0
        self.one_chest_pct = 0.0
        self.two_chest_pct = 0.0
        self.three_chest_pct = 0.0

#endregion

#region Bot class
class BorealChestRunner():
    def __init__(self):
        super().__init__()
        self.bot_name = "Boreal Chest Runner"
        self.window_module = ImGui.WindowModule(self.bot_name, window_name=self.bot_name, window_flags=PyImGui.WindowFlags.AlwaysAutoResize)

        self.inventory_config = InventoryConfig()
        self.sell_config = SellConfig()
        self.id_config = IDConfig()
        self.path_points = PathPoints()
        self.run_stats = RunStats()
        self.body_block_helper = BodyBlockHelper()

        self.is_script_running = False  
        self.log_to_console = True
        self.log_level = LogLevel.INFO
        self.chest_number_target = 3
        self.chest_run_active = False
        self.skill_routine_suspended = False
        self.has_reentered = False
        self.dervish = False
        self.anniversary_panel_enabled = False
        self.ping_handler = Py4GW.PingHandler()
        self.chest_proximity_threshold = 2500
        self.current_chest_path_index = 0
        self.interacting_with_chest = False

        self.boreal_station_id = outpost_name_to_id["Boreal Station"]
        self.ice_cliff_chasms_id = explorable_name_to_id["Ice Cliff Chasms"]
#endregion

    def __log(self, message: str, level: int = LogLevel.INFO):
        if not self.log_to_console or self.log_level > level:
            return
        
        match level:
            case LogLevel.DEBUG:
                caller = getframeinfo(stack()[2][0])
                message = f"{caller.function}:{caller.lineno-1} - {message}"
                Py4GW.Console.Log(self.bot_name, message, Py4GW.Console.MessageType.Debug)
            case LogLevel.INFO:
                Py4GW.Console.Log(self.bot_name, message, Py4GW.Console.MessageType.Info)
            case LogLevel.WARNING:
                Py4GW.Console.Log(self.bot_name, message, Py4GW.Console.MessageType.Warning)
            case LogLevel.ERROR:
                Py4GW.Console.Log(self.bot_name, message, Py4GW.Console.MessageType.Error)
            case _:
                Py4GW.Console.Log(self.bot_name, message, Py4GW.Console.MessageType.Info)

    def log_debug(self, message: str):
        self.__log(message, LogLevel.DEBUG)

    def log_info(self, message: str):
        self.__log(message, LogLevel.INFO)

    def log_warning(self, message: str):
        self.__log(message, LogLevel.WARNING)
    
    def log_error(self, message: str):
        self.__log(message, LogLevel.ERROR)

    def stop_environment(self):
        self.chest_run_active = False
        self.is_script_running = False
        GLOBAL_CACHE.Coroutines.clear()

    def draw_window(self):
        try:
            if self.window_module.first_run:
                PyImGui.set_next_window_size(self.window_module.window_size[0], self.window_module.window_size[1])     
                PyImGui.set_next_window_pos(self.window_module.window_pos[0], self.window_module.window_pos[1])
                self.window_module.first_run = False

            if PyImGui.begin(self.window_module.window_name, self.window_module.window_flags):
                self.log_to_console = PyImGui.checkbox("Log to Console", self.log_to_console)
                self.log_level = PyImGui.combo("Log Level", self.log_level, ["Debug", "Info", "Warning", "Error"])
                self.chest_number_target = PyImGui.combo("Chest target", self.chest_number_target-1, ["1", "2", "3"])+1
                self.id_config.id_golds = PyImGui.checkbox("ID Golds", self.id_config.id_golds)

                # Display run stats
                if PyImGui.collapsing_header("Run stats", PyImGui.TreeNodeFlags.DefaultOpen):
                    PyImGui.text(f"Runs completed: {self.run_stats.runs_completed}")
                    PyImGui.text(f"Chests found: {self.run_stats.chests_found}")
                    PyImGui.text(f"Average chests per run: {self.run_stats.average_chests_per_run:.2f}")
                    PyImGui.text(f"Chests per hour: {self.run_stats.chests_per_hour:.2f}")
                    PyImGui.text(f"Runs with 0 chests: {self.run_stats.zero_chest_cnt} ({self.run_stats.zero_chest_pct:.1f}%)")
                    PyImGui.text(f"Runs with 1 chest: {self.run_stats.one_chest_cnt} ({self.run_stats.one_chest_pct:.1f}%)")
                    PyImGui.text(f"Runs with 2 chests: {self.run_stats.two_chest_cnt} ({self.run_stats.two_chest_pct:.1f}%)")
                    PyImGui.text(f"Runs with 3 chests: {self.run_stats.three_chest_cnt} ({self.run_stats.three_chest_pct:.1f}%)")
                    PyImGui.text(f"Total gold earned: {self.run_stats.total_gold_earned}")
                    PyImGui.text(f"Total gold items identified: {self.run_stats.total_gold_items_identified}")

                button_text = "Start script" if not self.is_script_running else "Stop script"
                if PyImGui.button(button_text):
                    self.is_script_running = not self.is_script_running  
                    if self.is_script_running:
                        GLOBAL_CACHE.Coroutines.append(self.movement_and_merchant_routine())
                        GLOBAL_CACHE.Coroutines.append(self.skill_routine())
                    else:
                        self.stop_environment()
            PyImGui.end()
        except Exception as e:
            Py4GW.Console.Log(self.bot_name, f"Error in draw_window: {str(e)}", Py4GW.Console.MessageType.Error)
            raise

#region Skill handling
    def load_skill_bar(self):
        primary_profession, _ = Agent.GetProfessionNames(Player.GetAgentID())

        skill_templates = {
            "Warrior":      "OQcR8Z6ucCimUnBAAAAAAAA",
            "Ranger":       "OgcR8Z6ucCimUnBAAAAAAAA",
            "Monk":         "OwcR8Z6ucCimUnBAAAAAAAA",
            "Necromancer":  "OAdR8Z6ucCimUnBAAAAAAAA",
            "Mesmer":       "OQdR8Z6ucCimUnBAAAAAAAA",
            "Elementalist": "OgdR8Z6ucCimUnBAAAAAAAA",
            "Assassin":     "OwBR8Z6ucCimUnBAAAAAAAA",
            "Ritualist":    "OAeR8Z6ucCimUnBAAAAAAAA",
            "Paragon":      "OQeR8Z6ucCimUnBAAAAAAAA",
            "Dervish":      "Ogei8xsMNudgdXSTqzkmBAAAAA"
        }

        template = skill_templates.get(primary_profession)
        if template:
            SkillBar.LoadSkillTemplate(template)

        if primary_profession == "Dervish":
            self.dervish = True
            self.log_info("Dervish detected, loading Dervish skill template.")

        yield from Routines.Yield.wait(500)

    def assassin_primary_or_secondary(self):
        primary_profession, secondary_profession = Agent.GetProfessionNames(Player.GetAgentID())
        if primary_profession != "Assassin" and secondary_profession != "Assassin":
            self.log_error("assassin_primary_or_secondary - This bot requires A/Any or Any/A to work, halting.")
            return False
        return True
    
    def get_enemies_near_spell_casting_range(self):
        player_pos = Player.GetXY()
        enemy_array = Routines.Agents.GetFilteredEnemyArray(player_pos[0],player_pos[1],Range.Spellcast.value + 400)
        return enemy_array

    def mountain_aloe_or_pinesoul_nearby(self):
        if not self.chest_run_active:
            return False

        enemy_array = self.get_enemies_near_spell_casting_range()
        for enemy in enemy_array:
            if Agent.GetPlayerNumber(enemy) in [Creatures.MOUNTAIN_ALOE, Creatures.MOUNTAIN_PINESOUL]:
                return True
        return False
    
    def many_enemies_or_avalanche_nearby(self):
        if not self.chest_run_active:
            return False

        enemy_array = self.get_enemies_near_spell_casting_range()
        if len(enemy_array) > 3:
            return True

        for enemy in enemy_array:
            if Agent.GetPlayerNumber(enemy) == Creatures.AVALANCHE: 
                return True
        return False

    def many_enemies_nearby(self):
        if not self.chest_run_active:
            return False

        enemy_array = self.get_enemies_near_spell_casting_range()
        return len(enemy_array) > 3
    
    def evaluate_skill_casting_status(self):
        """Returns True if the bot can cast skills, False otherwise."""
        if not self.chest_run_active:
            self.skill_routine_suspended = True
            yield from Routines.Yield.wait(1000)
            return False
        elif Map.IsMapLoading():
            yield from Routines.Yield.wait(3000)
            return False
        elif not Routines.Checks.Map.MapValid():
            yield from Routines.Yield.wait(3000)
            return False
        elif not (Map.IsMapReady() and Party.IsPartyLoaded() and Map.IsExplorable()):
            yield from Routines.Yield.wait(1000)
            return False
        elif not Routines.Checks.Skills.CanCast():
            yield from Routines.Yield.wait(1000)
            return False
        else:
            self.skill_routine_suspended = False
            return True
        
    def cast_skill(self, skill_id: int, aftercast_delay_ms: int = -1):
        """Cast a skill by its ID, with optional logging and aftercast delay."""
        log_to_console = self.log_to_console

        if Routines.Sequential.Skills.CastSkillID(skill_id, log_to_console):
            if aftercast_delay_ms > 0:
                yield from Routines.Yield.wait(aftercast_delay_ms)
            return True
        return False
    
    def hp_is_critical(self):
        max_health = Agent.GetMaxHealth(Player.GetAgentID())
        if max_health <= 0:
            return False
        current_health = Agent.GetHealth(Player.GetAgentID()) * max_health
        current_health_pct = current_health / max_health * 100
        return current_health_pct < 40
    
    def player_has_buff(self, buff_id):
        player_id = Player.GetAgentID()
        return Routines.Checks.Effects.HasBuff(player_id, buff_id)
    
    def skill_routine(self):
        """Routine for handling skill casting based on conditions."""
        dwarven_stability = GLOBAL_CACHE.Skill.GetID("Dwarven_Stability")
        dash = GLOBAL_CACHE.Skill.GetID("Dash")
        i_am_unstoppable = GLOBAL_CACHE.Skill.GetID("I_Am_Unstoppable")
        zealous_renewal = GLOBAL_CACHE.Skill.GetID("Zealous_Renewal")
        pious_haste = GLOBAL_CACHE.Skill.GetID("Pious_Haste")
        shadow_form = GLOBAL_CACHE.Skill.GetID("Shadow_Form")
        feigned_neutrality = GLOBAL_CACHE.Skill.GetID("Feigned_Neutrality")

        shadow_form_available = SkillBar.IsSkillLearnt(shadow_form)
        feigned_neutrality_available = SkillBar.IsSkillLearnt(feigned_neutrality)

        while True:
            can_cast = yield from self.evaluate_skill_casting_status()
            if not can_cast:
                yield from Routines.Yield.wait(500)
                continue
            
            yield from self.cast_skill(dwarven_stability, aftercast_delay_ms=500)

            if not self.dervish:
                yield from self.cast_skill(dash, aftercast_delay_ms=200)
            else:
                yield from self.cast_skill(zealous_renewal, aftercast_delay_ms=200)
                if self.player_has_buff(zealous_renewal):
                    yield from self.cast_skill(pious_haste, aftercast_delay_ms=200)

            if self.mountain_aloe_or_pinesoul_nearby():
                yield from self.cast_skill(i_am_unstoppable, aftercast_delay_ms=200)
            
            # Only cast shadow form when near end and surrounded
            if shadow_form_available and self.interacting_with_chest and self.current_chest_path_index > 7 and self.many_enemies_or_avalanche_nearby():
                #self.log_debug("Casting Shadow Form due to many enemies near chest.")
                yield from self.cast_skill(shadow_form, aftercast_delay_ms=2000)

            if feigned_neutrality_available and self.interacting_with_chest and self.hp_is_critical():
                if (yield from self.cast_skill(feigned_neutrality, aftercast_delay_ms=500)):
                    # Using skills deactivates feigned neutrality
                    yield from Routines.Yield.wait_until(lambda: self.interacting_with_chest is False, 9000)
            
            yield

            
#endregion

#region Inventory handling
    def get_id_kits_to_buy(self):
        count_of_id_kits = Inventory.GetModelCount(ModelID.Superior_Identification_Kit.value) #5899 model for ID kit
        id_kits_to_buy = self.inventory_config.keep_id_kit - count_of_id_kits
        return id_kits_to_buy
    
    def get_items_to_identify(self):
        bags_to_check = ItemArray.CreateBagList(1, 2, 3, 4)
        bag_item_array = ItemArray.GetItemArray(bags_to_check)

        in_excepted_items = lambda item_id: (
            Item.Rarity.IsWhite(item_id) # Remote white items
            or (Item.Rarity.IsGold(item_id) and not self.id_config.id_golds) # Remove gold items if configured not to identify them
        )
        items_to_identify = ItemArray.Filter.ByCondition(bag_item_array, lambda item_id: not Item.Usage.IsIdentified(item_id) and not in_excepted_items(item_id))
        
        return items_to_identify if len(items_to_identify) > 0 else []

    def item_is_super_rare(self, item_id):
        rare_enum = next((x for x in self.inventory_config.rare_items_to_keep if x == item_id), None)
        if not rare_enum:
            return False

        ConsoleLog(self.bot_name, f"Keeping rare item: {rare_enum.name}", Console.MessageType.Success)
        return True
    
    def get_items_to_sell_and_keep_super_rare_items(self):
        bags_to_check = ItemArray.CreateBagList(1, 2, 3, 4)
        bag_item_array = ItemArray.GetItemArray(bags_to_check)
        banned_models = {ModelID.Salvage_Kit.value,ModelID.Superior_Identification_Kit.value,ModelID.Lockpick.value}

        items_to_sell = ItemArray.Filter.ByCondition(
            bag_item_array,
            lambda item_id: 
                not self.item_is_super_rare(item_id) 
                and not self.item_is_super_rare(Item.GetModelID(item_id)) 
                and Item.GetModelID(item_id) not in banned_models 
                and Item.Usage.IsIdentified(item_id))
        
        return items_to_sell
    
    def sell_items(self):
        items_to_sell = self.get_items_to_sell_and_keep_super_rare_items()
        if len(items_to_sell) < 1:
            return
        
        log_to_console = self.log_to_console
        self.log_info(f"Selling {len(items_to_sell)} items.")
        yield from Routines.Yield.Merchant.SellItems(items_to_sell, log_to_console)
          
    def get_items_to_deposit(self):
        bags_to_check = ItemArray.CreateBagList(1,2,3,4)
        items_to_deposit = ItemArray.GetItemArray(bags_to_check)
        banned_models = {ModelID.Salvage_Kit.value,ModelID.Superior_Identification_Kit.value,ModelID.Lockpick.value}
        items_to_deposit = ItemArray.Filter.ByCondition(items_to_deposit, lambda item_id: Item.GetModelID(item_id) not in banned_models)
        return items_to_deposit

    def needs_to_handle_inventory(self):
        free_slots_in_inventory = Inventory.GetFreeSlotCount()
        count_of_id_kits = Inventory.GetModelCount(ModelID.Superior_Identification_Kit.value) #5899 model for ID kit

        needs_to_handle_inventory = False
        if free_slots_in_inventory < self.inventory_config.leave_free_slots:
            self.log_info("Fewer free slots than configured minimum")
            needs_to_handle_inventory = True
        if count_of_id_kits < self.inventory_config.keep_id_kit:
            self.log_info("Fewer id kits than configured minimum")
            needs_to_handle_inventory = True
        
        return needs_to_handle_inventory
    
    def get_current_ping_based_throttle_value(self):
        """Returns a ping-based throttle value for inventory operations."""
        return self.ping_handler.GetCurrentPing() * 10
    
    def get_max_ping_based_throttle_value(self):
        """Returns a ping-based maximum throttle value for inventory operations."""
        return self.ping_handler.GetMaxPing() * 10

    def deposit_items_to_storage(self):
        """Deposits items to storage if there are free slots available."""
        log_to_console = self.log_to_console
        total_items, total_capacity = Inventory.GetStorageSpace(Anniversary_panel=self.anniversary_panel_enabled)
        
        self.log_debug(f"Storage total items: {total_items}, total capacity: {total_capacity}")
        free_slots = total_capacity - total_items

        if free_slots < 1:
            self.log_warning("No free slots in storage, skipping deposit.")
            return False

        items_to_deposit = self.get_items_to_deposit()

        if free_slots < len(items_to_deposit):
            self.log_warning(f"Not enough free slots to deposit all items. Free slots: {free_slots}, items to deposit: {len(items_to_deposit)}")
            items_to_deposit = items_to_deposit[:free_slots]
            return False

        yield from Routines.Yield.Items.DepositItems(items_to_deposit,log_to_console, Anniversary_panel=self.anniversary_panel_enabled, wait_time_between_items_ms=self.get_current_ping_based_throttle_value())
        return True

    def go_to_merchant(self):
        log_to_console = self.log_to_console
        if log_to_console:
            self.log_info("Going to merchant.")
        yield from Routines.Yield.Agents.InteractWithAgentXY(7395, -24899, timeout_ms=15000)

    def buy_id_kits(self):
        log_to_console = self.log_to_console
        if log_to_console:
            self.log_info("Buying ID kits.")
        yield from Routines.Yield.Merchant.BuyIDKits(self.get_id_kits_to_buy(),log_to_console)
        yield from Routines.Yield.wait(2500)

    def identify_items(self):
        items_to_idenfity = self.get_items_to_identify()
        if len(items_to_idenfity) < 1:
            return
        
        log_to_console = self.log_to_console
        self.log_info(f"IDing {len(items_to_idenfity)} items.")
        yield from Routines.Yield.Items.IdentifyItems(items_to_idenfity, log_to_console)
        self.run_stats.total_gold_items_identified += len([x for x in items_to_idenfity if Item.Rarity.IsGold(x)])

    def deposit_gold(self):
        log_to_console = self.log_to_console
        self.log_info("Depositing gold.")
        # Wait a few seconds before depositing to allow gold from selling to be added to inventory
        yield from Routines.Yield.wait(3000)
        gold_before_deposit = GLOBAL_CACHE.Inventory.GetGoldOnCharacter()
        deposited = yield from Routines.Yield.Items.DepositGold(self.inventory_config.keep_gold_amount, log=log_to_console)
        if not deposited:
            return
        self.run_stats.total_gold_earned += gold_before_deposit - self.inventory_config.keep_gold_amount

    def handle_inventory(self):
        """Handles inventory by going to merchant, buying kits, identifying, salvaging, selling, depositing gold and items."""
        yield from self.go_to_merchant()
        yield from self.buy_id_kits()
        yield from self.identify_items()
        yield from self.sell_items()
        yield from self.buy_id_kits()
        yield from self.deposit_gold()
        more_free_slots_available = yield from self.deposit_items_to_storage()
        
        if not more_free_slots_available:
            self.log_info("Not enough free slots available after handling inventory")
            return False
        
        return True
#endregion

#region Movement logic
    def skill_routine_suspended_guard(self):
        if not self.skill_routine_suspended:
            return False
        
        self.log_debug("Skill routine suspended")
        return True

    def resign_and_wait_for_boreal_station_loaded(self):
        # This waits for 3 seconds (more than enough) 
        # or until the skill routine has been marked as suspended.
        yield from Routines.Yield.wait_until(lambda: self.skill_routine_suspended_guard(), 3000)
        self.log_info("Run finished, resigning")
        Player.SendChatCommand("resign") 
        # Wait until resign has taken effect
        yield from Routines.Yield.wait_until(lambda: GLOBAL_CACHE.Party.IsPartyDefeated(), 10000)
        GLOBAL_CACHE.Party.ReturnToOutpost()
        yield from Routines.Yield.Map.WaitforMapLoad(self.boreal_station_id)

    def pre_run_checks(self):
        """Verify skillbar, inventory, lockpick checks before starting."""
        if not self.assassin_primary_or_secondary():
            self.log_error("Skillbar not loaded, halting.")
            self.stop_environment()
            return False

        self.log_info("Skillbar loaded")

        if Inventory.GetFreeSlotCount() < 1:
            self.log_error("No free slots in inventory, halting.")
            self.stop_environment()
            return False

        if Inventory.GetModelCount(ModelID.Lockpick) < 1:
            self.log_error("No lockpicks in inventory, halting.")
            self.stop_environment()
            return False

        return True
    
    def get_nearby_chest_agent_id(self) -> int:
        return Routines.Agents.GetNearestChest(self.chest_proximity_threshold)

    def is_chest_found_nearby(self) -> bool:
        return Routines.Agents.GetNearestChest(self.chest_proximity_threshold) != 0
    
    def suspend_execution_until_map_is_valid(self):
        """Suspend execution until the map is valid."""
        while not Routines.Checks.Map.MapValid():
            yield from Routines.Yield.wait(1000)
        yield

    def safe_increment_chest_path_index(self):
        if self.current_chest_path_index < len(self.path_points.path_points_to_look_for_chest) - 1:
            self.current_chest_path_index += 1

    def follow_path_until_chest_discovered(self, exit_condition):
        if self.current_chest_path_index > len(self.path_points.path_points_to_look_for_chest) - 1:
            return False

        # Set path_coords to remaining path points
        path_coords = self.path_points.path_points_to_look_for_chest[self.current_chest_path_index:]

        def progress_cb(_):
            self.safe_increment_chest_path_index()
            self.log_debug(f"current_chest_path_index: {self.current_chest_path_index}")

        yield from Routines.Yield.Movement.FollowPath(
            path_coords, 
            progress_callback=progress_cb, 
            custom_exit_condition=exit_condition, 
            timeout=30000)

    def exit_and_re_enter_for_resign_position(self, exit_outpost_path: list[tuple[float, float]]):
        self.log_info("Exiting outpost from starting position")
        yield from Routines.Yield.Movement.FollowPath(exit_outpost_path, custom_exit_condition=lambda: Map.IsMapLoading())
        yield from Routines.Yield.Map.WaitforMapLoad(self.ice_cliff_chasms_id)

        self.log_info("Re-entering outpost to get resign position")
        yield from Routines.Yield.Movement.FollowPath(self.path_points.path_points_to_reenter_outpost, custom_exit_condition=lambda: Map.IsMapLoading())
        yield from Routines.Yield.Map.WaitforMapLoad(self.boreal_station_id)
        self.has_reentered = True
        yield from Routines.Yield.wait(250)

    def execute_chest_run(self, chests_to_look_for):
        self.chest_run_active = True
        previous_chest_agent_id = 0
        self.body_block_helper.reset()
        exit_condition = lambda: self.is_chest_found_nearby() or self.body_block_helper.body_block_detected(logger=self.log_warning)
        chest_cnt_this_run = 0

        for i in range (chests_to_look_for):
            yield from self.follow_path_until_chest_discovered(exit_condition)
            current_chest_agent_id = self.get_nearby_chest_agent_id()

            # no chest found or stuck when running
            if current_chest_agent_id == 0 or self.body_block_helper.stuck:
                break

            if current_chest_agent_id == previous_chest_agent_id:
                continue

            self.interacting_with_chest = True
            self.log_info(f"Chest #{i+1} found")
            self.body_block_helper.reset()
            yield from Routines.Yield.Agents.InteractWithNearestChest(
                timeout_ms=20000, 
                custom_exit_condition=lambda: self.body_block_helper.body_block_detected(logger=self.log_warning))
            self.interacting_with_chest = False

            # stuck during interaction with chest
            if self.body_block_helper.stuck:
                break
            
            chest_cnt_this_run += 1
            # Skip to next path point after finding a chest
            self.safe_increment_chest_path_index()
            # If we were going to the last point then this is the final chest.
            # This avoids wasting time by running back to the last point when no more chests will be found.
            if self.current_chest_path_index == len(self.path_points.path_points_to_look_for_chest) - 1:
                self.log_debug("Early exit because chest was just found near last point")
                break

            previous_chest_agent_id = current_chest_agent_id
            # Set exit condition to find a different chest than the last one found
            self.body_block_helper.reset()
            exit_condition = lambda: (self.is_chest_found_nearby() and self.get_nearby_chest_agent_id() != previous_chest_agent_id) or self.body_block_helper.body_block_detected(logger=self.log_warning)

            self.log_debug(f"current_chest_path_index: {self.current_chest_path_index}")

        self.chest_run_active = False
        self.current_chest_path_index = 0
        return chest_cnt_this_run
    
    def handle_inventory_if_needed(self):
        enough_space_to_continue = True
        merchant_visited = False

        if self.needs_to_handle_inventory():
            self.log_info("Inventory needs handling before starting run")
            enough_space_to_continue = yield from self.handle_inventory()
            merchant_visited = True

        return enough_space_to_continue, merchant_visited
    
    def calculate_chest_run_stats(self, chest_cnt_this_run: int):
        self.run_stats.chests_found += chest_cnt_this_run
        self.run_stats.runs_completed += 1
        self.run_stats.chests_per_hour = self.run_stats.chests_found / ((time.time() - self.run_stats.start_time) / 3600)
        self.run_stats.average_chests_per_run = self.run_stats.chests_found / self.run_stats.runs_completed if self.run_stats.runs_completed > 0 else 0.0

        match chest_cnt_this_run:
            case 0:
                self.run_stats.zero_chest_cnt += 1
            case 1:
                self.run_stats.one_chest_cnt += 1
            case 2:
                self.run_stats.two_chest_cnt += 1
            case 3:
                self.run_stats.three_chest_cnt += 1

        self.run_stats.zero_chest_pct = (self.run_stats.zero_chest_cnt/self.run_stats.runs_completed) * 100
        self.run_stats.one_chest_pct = (self.run_stats.one_chest_cnt/self.run_stats.runs_completed) * 100
        self.run_stats.two_chest_pct = (self.run_stats.two_chest_cnt/self.run_stats.runs_completed) * 100
        self.run_stats.three_chest_pct = (self.run_stats.three_chest_cnt/self.run_stats.runs_completed) * 100

    def travel_to_boreal_station_if_not_there(self):
        if Map.GetMapID() != self.boreal_station_id:
            yield from Routines.Yield.Map.TravelToOutpost(self.boreal_station_id, self.log_to_console)

    def movement_and_merchant_routine(self):
        """Routine for movement, finding chests, and handling inventory"""
        self.run_stats.start_time = time.time()

        while True:
            yield from self.suspend_execution_until_map_is_valid()
            # Map travel to Boreal Station if not already there
            yield from self.travel_to_boreal_station_if_not_there()
            yield from self.load_skill_bar()

            if not self.pre_run_checks():
                self.stop_environment()
                continue

            enough_space_to_continue, merchant_visited = yield from self.handle_inventory_if_needed()
            if not enough_space_to_continue:
                self.log_error("Inventory not handled, halting.")
                self.stop_environment()
                continue
            
            if not self.has_reentered:
                # Gets the best starting path based on position when starting script.
                exit_outpost_path = self.path_points.path_points_to_exit_outpost
                pos = Player.GetXY()
                if pos and Utils.Distance(pos, self.path_points.resign_point) < 200:
                    exit_outpost_path = self.path_points.path_points_to_exit_outpost_after_resign
                elif merchant_visited:
                    exit_outpost_path = self.path_points.path_points_to_exit_outpost_after_merchant

                yield from self.exit_and_re_enter_for_resign_position(exit_outpost_path)
                merchant_visited = False  # Reset if position was used for getting resign position

            if merchant_visited:
                self.log_info("Exiting outpost from merchant position")
                yield from Routines.Yield.Movement.FollowPath(self.path_points.path_points_to_exit_outpost_after_merchant, custom_exit_condition=lambda: Map.IsMapLoading())
            else:
                self.log_info("Exiting outpost from resign position")
                yield from Routines.Yield.Movement.FollowPath(self.path_points.path_points_to_exit_outpost_after_resign, custom_exit_condition=lambda: Map.IsMapLoading())
            
            yield from Routines.Yield.Map.WaitforMapLoad(self.ice_cliff_chasms_id)

            chests_to_look_for = self.chest_number_target
            self.log_info(f"Run starting, looking for {chests_to_look_for} chests")
            chest_cnt_this_run = yield from self.execute_chest_run(chests_to_look_for)
            if chest_cnt_this_run == 0:
                self.log_error("No chests found")
            
            self.calculate_chest_run_stats(chest_cnt_this_run)
            yield from self.resign_and_wait_for_boreal_station_loaded()

#endregion

#region Entry point
boreal_chest_runner = BorealChestRunner()

def main():
    boreal_chest_runner.draw_window()

if __name__ == "__main__":
    main()

#endregion