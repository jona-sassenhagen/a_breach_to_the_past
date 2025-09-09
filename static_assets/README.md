There are matching *.png and *.txt files.

Each png file consists of a grid of 16x16 tiles.
The corresponding txt file has in TSV format (e.g., newlines and tabs) the names for each element. 

E.g., a grid might be:

small_tree	tall_tree
hole	stone

Then the top left 16x16 square in the PNG would be a small tree, the bottom left 16x16 square a stone, etc.

## Adding new files

New crops can be generated with the following command:

bash extract_slice_v4.sh ~/Downloads/DawnLike/GUI/GUI1.png static_assets \
  --x0 0 --y0 1 --x1 4 --y1 1 --res 16x16 --coords tiles --prefix hearts --verbose
