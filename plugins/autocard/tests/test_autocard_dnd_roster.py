from __future__ import annotations

import io
import math
import unittest
from unittest.mock import patch
from PIL import Image

from autocard.extractors import _complete_dnd_skills, DND_SKILL_PARENTS
from autocard.models import Character, PokemonCompanion, PokemonMove
from autocard.ooxml import Cell, Worksheet
from autocard.render import render_pngs, render_pokemon_roster


class DndAndRosterTests(unittest.TestCase):
    def test_owlbear_totals_and_proficiency_use_labelled_columns(self):
        cells = {name: Cell(name, value, None, None) for name, value in {
            'C48':'奥秘','B48':'O','F48':2,'I48':6,
            'C49':'历史','B49':'🅞','I49':8,'C15':'体质','B15':'O',
        }.items()}
        sheet = Worksheet('主要','visible','',cells,None)
        class Book:
            def get_sheet(self, name): return sheet
        skills, formulas, saves = {'奥秘':2}, {}, {}
        _complete_dnd_skills(Book(),'主要',{'智力':11,'熟练':4},skills,formulas,saves,owlbear=True)
        self.assertEqual(skills['奥秘'],6)
        self.assertEqual(formulas['奥秘'],'pbCalc(2,1,智力)')
        self.assertEqual(formulas['历史'],'pbCalc(0,2,智力)')
        self.assertEqual(saves['体质'],1)
        self.assertEqual(saves['力量'],0)
        self.assertEqual(len(formulas),18)

    def test_generic_totals_are_not_added_to_ability_twice(self):
        class Book:
            def get_sheet(self,name): return None
        skills, formulas, saves = {'历史':7,'奥秘':-1}, {}, {}
        _complete_dnd_skills(Book(),'主要',{'智力':13},skills,formulas,saves)
        self.assertEqual(formulas['历史'],'pbCalc(6,0,智力)')
        self.assertEqual(formulas['奥秘'],'pbCalc(-2,0,智力)')

    def test_large_roster_includes_last_companion_and_every_move(self):
        character = Character('test.xlsx','xlsx','POKEMON-TRPG','pokemon','test','test','test',name='队伍测试')
        character.pokemon = [PokemonCompanion(name=f'伙伴{i}',species='种族',stats={'攻击':i},
                                moves=[PokemonMove(f'招式{j}') for j in range(14)]) for i in range(1,26)]
        drawn=[]
        from PIL import ImageDraw
        original=ImageDraw.ImageDraw.text
        def track(draw,xy,text,*args,**kwargs):
            drawn.append(str(text)); return original(draw,xy,text,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',track):
            image=render_pokemon_roster(character)
        self.assertTrue(any('伙伴25' in text for text in drawn))
        self.assertTrue(any('招式13' in text for text in drawn))
        self.assertGreater(image.height,1000)
        image.close()
        with patch('autocard.render.render_character',return_value=Image.new('RGB',(10,10))), \
             patch('autocard.render.CompactSheet.render_pokemon_companion',side_effect=AssertionError('must use summary')):
            images=render_pngs(character)
        self.assertEqual(len(images),2)
        with Image.open(io.BytesIO(images[-1])) as combined:
            self.assertGreater(combined.height,1000)


if __name__ == '__main__': unittest.main()
